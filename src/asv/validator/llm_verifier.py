"""LLM Verifier — source-grounded claim verification.

Tier 0.1 removed ``verify_claim`` (the plausibility check) from this module.
It asked a small model whether a sentence *sounded* right and returned a
confidence score; on the measured corpus that path produced 217 of 224 "passes"
with ``sources_used: []``. It is not deleted-but-kept-around: the primitive
itself is gone, because deleting the callers while leaving the primitive
guarantees it comes back.

What remains is the only verification ASV performs: retrieve passages from the
cited source, ask the model to judge the claim against *those passages*, and
then **check that the quotes it returned actually appear in them** (Tier 0.5).
A verdict whose quote cannot be found in the source is downgraded to an
abstention rather than trusted — VALUE_PROPOSITION.md §2.4(c) documents this
system inventing its own evidence once already.
"""

import logging
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

from rapidfuzz import fuzz
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from asv.core.models import EvidenceSpan
from asv.core.verdicts import NotCheckableReason, Verdict
from asv.extraction.llm_client import LLMClient

from .config import (
    QUOTE_VERIFICATION_MIN_CHARS,
    QUOTE_VERIFICATION_THRESHOLD,
    RAG_TOP_K,
    RAG_SIMILARITY_THRESHOLD,
    SOURCE_VERIFICATION_PROMPT_VERSION,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


#: Tolerant mapping for the verdict token the model returns. Models drift
#: toward natural-language synonyms; an unrecognised token must abstain rather
#: than be coerced into a judgment.
_VERDICT_ALIASES: Dict[str, Verdict] = {
    "substantiated": Verdict.SUBSTANTIATED,
    "supported": Verdict.SUBSTANTIATED,
    "partially_substantiated": Verdict.PARTIALLY_SUBSTANTIATED,
    "partially substantiated": Verdict.PARTIALLY_SUBSTANTIATED,
    "partial": Verdict.PARTIALLY_SUBSTANTIATED,
    "partially_supported": Verdict.PARTIALLY_SUBSTANTIATED,
    "not_substantiated": Verdict.NOT_SUBSTANTIATED,
    "not substantiated": Verdict.NOT_SUBSTANTIATED,
    "unsupported": Verdict.NOT_SUBSTANTIATED,
    "insufficient": Verdict.NOT_SUBSTANTIATED,
    "contradicted": Verdict.CONTRADICTED,
    "refuted": Verdict.CONTRADICTED,
    "contradicts": Verdict.CONTRADICTED,
}

_VALID_ROLES = ("supporting", "contradicting", "nearest_relevant")


def _normalise_with_map(text: str) -> Tuple[str, List[int]]:
    """Lowercase, drop punctuation, collapse whitespace — keeping an index map.

    The map lets a match in normalised space be reported as character offsets
    into the *original* source text, so the frontend can highlight the real
    passage. PDF extraction produces smart quotes, soft hyphens and ligatures
    that no LLM reproduces faithfully, which is why matching cannot be literal.
    """
    norm_chars: List[str] = []
    index_map: List[int] = []
    prev_space = True  # suppress leading space
    for i, ch in enumerate(unicodedata.normalize("NFKC", text)):
        if ch.isspace():
            if not prev_space:
                norm_chars.append(" ")
                index_map.append(i)
                prev_space = True
            continue
        if ch.isalnum():
            norm_chars.append(ch.lower())
            index_map.append(i)
            prev_space = False
        # punctuation is dropped entirely
    return "".join(norm_chars).strip(), index_map


def _normalise(text: str) -> str:
    return _normalise_with_map(text)[0]


class LLMVerifier:
    """Source-grounded claim verification (retrieval + judgment + quote check)."""

    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client
        self.vectorizer = TfidfVectorizer(
            max_features=1000,
            stop_words='english',
            ngram_range=(1, 2)
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def verify_claim_against_source(
        self,
        claim_text: str,
        source_text: str,
        source_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Verify a claim against source text using RAG + LLM.

        Returns a dict carrying a ``Verdict``, an optional
        ``NotCheckableReason``, a confidence (``None`` for abstentions), and a
        list of ``EvidenceSpan``. Never returns a judgment without at least one
        verbatim-verified span — ``ValidationResult`` would refuse to be
        constructed from it anyway.
        """
        url = source_url or ""

        chunks = self._split_into_chunks(source_text)
        if not chunks:
            return self._abstain(
                NotCheckableReason.RETRIEVAL_EMPTY,
                "The source text could not be split into passages to search.",
                rag_chunks=[],
            )

        relevant_chunks = self._retrieve_relevant_chunks(claim_text, chunks)
        if not relevant_chunks:
            # Tier 0.5 forces the Tier 2.4 fix early: with nothing retrieved
            # there is no span to attach, so this state is unconstructible as a
            # judgment. It hit 12 of 22 downloaded claims in the measured run
            # and was reported as a *failed claim*, which it is not — it is a
            # retrieval failure, and the honest answer is that we could not
            # check the claim.
            return self._abstain(
                NotCheckableReason.RETRIEVAL_EMPTY,
                (
                    f"No passage in the source scored above the retrieval threshold "
                    f"({RAG_SIMILARITY_THRESHOLD}) for this claim. This is a retrieval "
                    f"failure, not evidence against the claim."
                ),
                rag_chunks=[],
            )

        prompt = self._build_source_verification_prompt(claim_text, relevant_chunks)
        try:
            response = self.llm_client.call_llm(
                prompt,
                response_format="json",
                task_name="source_grounded_verification",
            )
        except Exception as e:
            logger.error(f"Source-grounded LLM verification failed: {e}")
            return self._abstain(
                NotCheckableReason.VALIDATION_ERROR,
                f"The verification model call failed: {e}",
                rag_chunks=relevant_chunks,
                error=str(e),
            )

        verdict = self._parse_verdict(response.get("verdict"))
        explanation = response.get("explanation") or "No explanation provided."
        if verdict is None:
            return self._abstain(
                NotCheckableReason.VALIDATION_ERROR,
                f"The verification model returned an unrecognised verdict "
                f"({response.get('verdict')!r}).",
                rag_chunks=relevant_chunks,
            )

        evidence, unverified = self._build_evidence(
            response.get("quotes") or [], relevant_chunks, source_text, url,
        )

        if not any(e.verified_verbatim for e in evidence):
            # Tier 0.5: an unverifiable quote destroys the entire value of the
            # finding ("checkable by a human in ten seconds"). Abstain rather
            # than ship a verdict whose evidence we could not locate.
            return self._abstain(
                NotCheckableReason.EVIDENCE_UNVERIFIABLE,
                (
                    "The verification model returned a verdict, but none of its quoted "
                    "passages could be located in the retrieved source text, so the "
                    "finding cannot be checked."
                ),
                rag_chunks=relevant_chunks,
                metadata={"unverified_quotes": unverified, "model_explanation": explanation},
            )

        confidence = self._parse_confidence(response.get("confidence"))
        return {
            "verdict": verdict,
            "not_checkable_reason": None,
            "confidence": confidence,
            "explanation": explanation,
            "evidence": evidence,
            "rag_chunks": relevant_chunks,
            "metadata": {
                "prompt_version": SOURCE_VERIFICATION_PROMPT_VERSION,
                "unverified_quotes": unverified,
            },
            "error": None,
        }

    # ------------------------------------------------------------------
    # Evidence handling (Tier 0.5)
    # ------------------------------------------------------------------

    def _build_evidence(
        self,
        quotes: List[Any],
        relevant_chunks: List[Dict[str, Any]],
        source_text: str,
        source_url: str,
    ) -> Tuple[List[EvidenceSpan], List[str]]:
        """Turn the model's quotes into verified evidence spans.

        Verification is against the **retrieved chunks**, not the whole
        document: if the model quotes something that was not in its own context
        window, it did not read it there. Character offsets are looked up
        separately in the full source so the UI can highlight the passage.
        """
        norm_chunks = [_normalise(c["text"]) for c in relevant_chunks]
        norm_source, index_map = _normalise_with_map(source_text)

        spans: List[EvidenceSpan] = []
        unverified: List[str] = []

        for item in quotes:
            if isinstance(item, dict):
                text = str(item.get("text") or item.get("quote") or "").strip()
                role = str(item.get("role") or "supporting").strip().lower()
            else:
                text = str(item or "").strip()
                role = "supporting"
            if not text:
                continue
            if role not in _VALID_ROLES:
                role = "supporting"

            norm_quote = _normalise(text)
            verified = False
            score: Optional[float] = None

            if len(norm_quote) >= QUOTE_VERIFICATION_MIN_CHARS:
                for nc in norm_chunks:
                    if norm_quote in nc:
                        verified, score = True, 1.0
                        break
                if not verified:
                    best = max(
                        (fuzz.partial_ratio(norm_quote, nc) for nc in norm_chunks),
                        default=0.0,
                    )
                    score = best / 100.0
                    verified = best >= QUOTE_VERIFICATION_THRESHOLD

            char_start = char_end = None
            if verified and norm_quote:
                pos = norm_source.find(norm_quote)
                if pos != -1 and pos + len(norm_quote) - 1 < len(index_map):
                    char_start = index_map[pos]
                    char_end = index_map[pos + len(norm_quote) - 1] + 1

            if not verified:
                unverified.append(text)
                continue

            retrieval_score = next(
                (c.get("score") for c in relevant_chunks if norm_quote in _normalise(c["text"])),
                None,
            )
            spans.append(EvidenceSpan(
                quote=text,
                role=role,  # type: ignore[arg-type]
                source_url=source_url or "unknown",
                retrieval_score=retrieval_score,
                char_start=char_start,
                char_end=char_end,
                verified_verbatim=True,
            ))
            if score is not None and score < 1.0:
                logger.debug(f"  Quote matched fuzzily at {score:.2f}: {text[:60]!r}")

        return spans, unverified

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def _split_into_chunks(self, text: str, chunk_size: int = 500) -> List[str]:
        """Split text into overlapping chunks for RAG retrieval."""
        if not text or len(text.strip()) == 0:
            return []

        sentences = text.replace('\n', ' ').split('. ')
        chunks: List[str] = []
        current_chunk: List[str] = []
        current_length = 0

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            sentence_length = len(sentence)

            if current_length + sentence_length > chunk_size and current_chunk:
                chunks.append('. '.join(current_chunk) + '.')
                current_chunk = [current_chunk[-1]] if current_chunk else []
                current_length = len(current_chunk[0]) if current_chunk else 0

            current_chunk.append(sentence)
            current_length += sentence_length

        if current_chunk:
            chunks.append('. '.join(current_chunk) + '.')

        return chunks

    def _retrieve_relevant_chunks(self, query: str, chunks: List[str]) -> List[Dict[str, Any]]:
        """Use TF-IDF similarity to retrieve relevant chunks for a claim.

        Note (Tier 2.1, not in scope here): TF-IDF misses paraphrase, which is
        exactly how citations get miscited. Replacing this with hybrid
        retrieval is the single biggest available improvement to judgment
        quality — but it is a Tier 2 change, and conflating it with Tier 0
        would make the abstention-rate movement impossible to attribute.
        """
        if len(chunks) == 0:
            return []

        try:
            all_texts = [query] + chunks
            tfidf_matrix = self.vectorizer.fit_transform(all_texts)

            query_vector = tfidf_matrix[0:1]  # type: ignore
            chunk_vectors = tfidf_matrix[1:]  # type: ignore
            similarities = cosine_similarity(query_vector, chunk_vectors)[0]

            relevant_indices = []
            for idx, score in enumerate(similarities):
                if score >= RAG_SIMILARITY_THRESHOLD:
                    relevant_indices.append((idx, score))

            relevant_indices.sort(key=lambda x: x[1], reverse=True)
            relevant_indices = relevant_indices[:RAG_TOP_K]

            results = []
            for idx, score in relevant_indices:
                results.append({'text': chunks[idx], 'score': float(score)})

            return results

        except Exception as e:
            # A vectorizer failure is a retrieval failure, not a licence to
            # judge against arbitrary chunks. Previously this returned the first
            # K chunks with a fabricated score of 0.5.
            logger.error(f"RAG retrieval error: {str(e)}")
            return []

    # ------------------------------------------------------------------
    # Prompt (Tier 0.5 / R10)
    # ------------------------------------------------------------------

    def _build_source_verification_prompt(
        self, claim: str, chunks: List[Dict[str, Any]]
    ) -> str:
        """Build the source-grounded verification prompt.

        Asks for a graded verdict rather than a boolean, and for quotes that are
        *copied* rather than reconstructed — the latter is what makes the
        verbatim check in ``_build_evidence`` meaningful rather than adversarial.
        """
        chunks_text = "\n\n".join([
            f"[Excerpt {i+1}, similarity={chunk['score']:.2f}]:\n{chunk['text']}"
            for i, chunk in enumerate(chunks)
        ])

        return f"""You are a citation auditor. Decide whether the cited source substantiates a claim.

Claim to verify: "{claim}"

Excerpts retrieved from the cited source:
{chunks_text}

Return JSON in exactly this shape:
{{
    "verdict": "substantiated" | "partially_substantiated" | "not_substantiated" | "contradicted",
    "confidence": 0.0-1.0,
    "explanation": "One or two sentences. Say what the source actually shows.",
    "quotes": [
        {{"text": "exact span copied character-for-character from an excerpt above",
          "role": "supporting" | "contradicting" | "nearest_relevant"}}
    ]
}}

Verdict definitions:
- "substantiated": the excerpts state the claim, or state something that entails it.
- "partially_substantiated": the excerpts support a WEAKER version of the claim — narrower
  population, hedged language, smaller effect, different time frame or setting. Use this
  rather than "substantiated" whenever the claim says more than the source does.
- "not_substantiated": the excerpts do not establish the claim. They may be about a
  related topic, or simply silent on it.
- "contradicted": the excerpts state something incompatible with the claim.

Rules about quotes — these are not optional:
- Every quote's "text" MUST be copied verbatim from the excerpts above. Do not paraphrase,
  summarise, reconstruct, correct, or re-punctuate. Quotes that cannot be found in the
  excerpts cause the whole verdict to be discarded.
- Give at least one quote for every verdict, including "not_substantiated": in that case
  quote the passage that comes CLOSEST to the claim and set "role": "nearest_relevant", so
  a human can see what the source does say.
- "contradicted" requires at least one quote with "role": "contradicting".

Judge only from the excerpts. Do not use outside knowledge about whether the claim is
true — the question is solely whether THIS source supports it.
"""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_verdict(raw: Any) -> Optional[Verdict]:
        if raw is None:
            return None
        return _VERDICT_ALIASES.get(str(raw).strip().lower().replace("-", "_"))

    @staticmethod
    def _parse_confidence(raw: Any) -> Optional[float]:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return None
        return min(max(value, 0.0), 1.0)

    @staticmethod
    def _abstain(
        reason: NotCheckableReason,
        explanation: str,
        *,
        rag_chunks: Optional[List[Dict[str, Any]]] = None,
        error: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        meta = {"prompt_version": SOURCE_VERIFICATION_PROMPT_VERSION}
        meta.update(metadata or {})
        return {
            "verdict": Verdict.NOT_CHECKABLE,
            "not_checkable_reason": reason,
            "confidence": None,
            "explanation": explanation,
            "evidence": [],
            "rag_chunks": rag_chunks or [],
            "metadata": meta,
            "error": error,
        }
