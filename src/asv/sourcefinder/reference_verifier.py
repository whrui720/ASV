"""Does the cited reference exist? — Tier 0.6 (docs/TIER0_PLAN.md §6).

VALUE_PROPOSITION.md §5/L1 calls existence checking "solved, free, table
stakes" and notes ASV does not do it — it goes straight to full-text
acquisition. Today a fabricated reference and a Wiley 403 produce identical
output (``download_successful: false``), which is the same defect Tier 0.2
fixes one layer up: two situations that imply opposite user actions, reported
identically.

**The safety property this module is built around.** Saying *"this reference
does not exist"* about a real reference is an allegation of fabrication — the
worst thing this tool can emit. Four controls, all mandatory:

1. **Never claim non-existence.** The status is ``NOT_FOUND_IN_INDEXES`` and the
   explanation names the indexes actually queried. The words *fabricated*,
   *hallucinated* and *fake* appear nowhere here or in the UI.
2. **Two-index quorum.** ``NOT_FOUND_IN_INDEXES`` requires at least
   ``REFCHECK_MIN_INDEXES_FOR_NOT_FOUND`` indexes to have *responded*. An
   outage yields ``UNVERIFIED``, never an accusation.
3. **Type routing.** Books, chapters, theses, reports, personal communications
   and pre-1970 work are systematically under-indexed and get
   ``UNINDEXED_BY_DESIGN``. Reference [1] of the test corpus — a chapter in
   *Harrison's Principles of Internal Medicine* — is the regression test.
4. **Always show the near miss.** Even when rejecting, the best candidate and
   its score are recorded, so a human sees *"it found the right paper, my year
   was wrong"* in ten seconds.

A side effect worth naming: SOURCE_ACQUISITION.md measures that 32 of 51 batches
have exactly one candidate URL, and ``AcademicPaperFinder`` only reaches
Crossref DOI recovery at step 3b, after everything else has failed. Running this
first hands the resolver a DOI up front on a corpus where **zero of 253
references carry an inline DOI**.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import unicodedata
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from rapidfuzz import fuzz

from asv.core.models import ReferenceCheck
from asv.core.verdicts import ReferenceStatus, RetractionStatus

from .config import (
    REFCHECK_AMBIGUOUS_TITLE_SIM,
    REFCHECK_MIN_INDEXED_YEAR,
    REFCHECK_MIN_INDEXES_FOR_NOT_FOUND,
    REFCHECK_VERIFIED_TITLE_SIM,
    REFCHECK_YEAR_TOLERANCE,
    UNINDEXED_REFERENCE_TYPES,
)
from .reference_text import normalise_reference
from .index_clients import BibliographicIndexes, IndexRecord, IndexResponse

logger = logging.getLogger(__name__)

_PUNCT_RE = re.compile(r"[^\w\s]+", re.UNICODE)
_WS_RE = re.compile(r"\s+")
_JOURNAL_STOPWORDS = {"of", "the", "and", "for", "in", "on", "a", "an", "&"}

# Textual tells for reference kinds the indexes do not carry. Used only when the
# LLM parse did not supply a type, and only to *explain an absence* — never to
# skip the lookup, since many book chapters do have DOIs.
_BOOKISH_RE = re.compile(
    r"\bIn:\s|\(\s*eds?\.?\s*\)|\bed\.\s|\beditors?\b|McGraw-?Hill|Springer-Verlag|"
    r"\bAcademic Press\b|\bUniversity Press\b|\bPublishers?\b|\bpersonal communication\b|"
    r"\bthesis\b|\bdissertation\b|\bPhD\b|\bM\.?Sc\.?\b",
    re.IGNORECASE,
)


def normalise_title(text: Optional[str]) -> str:
    """Aggressive normalisation for comparison.

    The bibliography strings this runs on are mangled by PDF extraction —
    ``Harrison<?>s Principles``, ``J Virol1999; 73``, ``tegument<?>capsid`` —
    so punctuation and digit/letter boundaries cannot be trusted.
    """
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", str(text))
    text = text.replace("‐", "-").replace("’", "'")
    text = _PUNCT_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text)
    return text.strip().lower()


def title_similarity(a: Optional[str], b: Optional[str]) -> float:
    """0..1 token-set similarity. Token-set (not ratio) because bibliography
    titles lose subtitles and gain journal fragments."""
    na, nb = normalise_title(a), normalise_title(b)
    if not na or not nb:
        return 0.0
    return fuzz.token_set_ratio(na, nb) / 100.0


def _is_subsequence(short: str, long: str) -> bool:
    """True if every character of ``short`` appears in ``long``, in order."""
    it = iter(long)
    return all(ch in it for ch in short)


def _abbreviation_matches(token: str, full: str) -> bool:
    """Does an abbreviated journal-name token stand for ``full``?

    Two forms cover essentially all journal abbreviations:
      * truncation — ``Virol`` -> ``Virology``, ``Med`` -> ``Medicine``
      * letter-dropping — ``Natl`` -> ``National``, ``Bull`` -> ``Bulletin``

    The second is why a prefix test alone is not enough: ``natl`` is not a
    prefix of ``national``. Subsequence matching is looser, so it is gated on a
    shared first letter and a minimum length to stop three-letter tokens
    matching everything.
    """
    if full.startswith(token) or token.startswith(full):
        return True
    return (
        len(token) >= 3
        and len(full) > len(token)
        and token[0] == full[0]
        and _is_subsequence(token, full)
    )


def journal_similarity(parsed_journal: Optional[str], candidate: Optional[str]) -> float:
    """Abbreviation-tolerant journal match: ``J Virol`` ~ ``Journal of Virology``.

    Every significant token of the (usually abbreviated) parsed journal must
    stand for some token in the candidate's full name. This corpus needs it:
    its references are uniformly abbreviated, and PDF extraction has run the
    abbreviations together with the year (``AdvExpMedBiol1994``).
    """
    a, b = normalise_title(parsed_journal), normalise_title(candidate)
    if not a or not b:
        return 0.0
    a_tokens = [t for t in a.split() if t not in _JOURNAL_STOPWORDS]
    b_tokens = [t for t in b.split() if t not in _JOURNAL_STOPWORDS]
    if not a_tokens or not b_tokens:
        return 0.0
    matched = sum(
        1 for t in a_tokens
        if any(_abbreviation_matches(t, bt) for bt in b_tokens)
    )
    return matched / len(a_tokens)


class ReferenceVerifier:
    """Checks each bibliography entry against the free indexes."""

    def __init__(
        self,
        parse_citation: Optional[Callable[[str], Dict[str, Any]]] = None,
        indexes: Optional[BibliographicIndexes] = None,
        cache_path: Optional[Path] = None,
    ):
        #: Reuses ``AcademicPaperFinder._parse_citation_with_llm`` when the
        #: orchestrator wires it in — that call is already made, already cached
        #: per citation string, and already paid for.
        self.parse_citation = parse_citation or (lambda _: {})
        self.indexes = indexes or BibliographicIndexes()
        self.cache_path = cache_path or _default_cache_path()
        self._cache: Dict[str, dict] = _load_cache(self.cache_path)
        self._cache_dirty = False

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def verify_all(
        self,
        citations: Dict[str, str],
        on_progress: Optional[Callable[[int, int, ReferenceCheck], None]] = None,
    ) -> Dict[str, ReferenceCheck]:
        """Audit every reference in the bibliography.

        Runs over *all* citations, not only those with claims attached: a
        complete bibliography audit is itself the deliverable
        (VALUE_PROPOSITION.md §9's free wedge), and "reference 34 exists but is
        cited nowhere" is a finding a reviewer wants.
        """
        out: Dict[str, ReferenceCheck] = {}
        total = len(citations)
        for i, (citation_id, raw_text) in enumerate(citations.items(), 1):
            try:
                check = self.verify(str(citation_id), raw_text or "")
            except Exception as e:  # never let the audit break the pipeline
                logger.warning(f"  Reference check failed for [{citation_id}]: {e}")
                check = ReferenceCheck(
                    citation_id=str(citation_id),
                    raw_citation_text=raw_text or "",
                    status=ReferenceStatus.UNVERIFIED,
                    explanation=f"Reference check errored: {e}",
                )
            out[str(citation_id)] = check
            if on_progress:
                on_progress(i, total, check)
        self.flush_cache()
        return out

    def verify(self, citation_id: str, raw_text: str) -> ReferenceCheck:
        key = _cache_key(raw_text)
        cached = self._cache.get(key)
        if cached is not None:
            data = dict(cached, citation_id=citation_id, raw_citation_text=raw_text)
            try:
                return ReferenceCheck(**data)
            except Exception:
                pass  # cache written by an older schema — recompute

        check = self._verify_uncached(citation_id, raw_text)
        self._cache[key] = check.model_dump(mode="json")
        self._cache_dirty = True
        return check

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _verify_uncached(self, citation_id: str, raw_text: str) -> ReferenceCheck:
        # Repair PDF-extraction damage before anything reads the string (F8).
        # ``ecitmatch`` is an exact match on journal|year|volume|page|author, so
        # a reference whose journal ran into its year ("DNA Cell Biol2002")
        # cannot match, and the fuzzy title comparison downstream is scored
        # against a title with the journal name welded onto its end.
        raw_text = normalise_reference(raw_text)
        parsed = self.parse_citation(raw_text) or {}
        if not isinstance(parsed, dict):
            parsed = {}

        doi = _clean_doi(parsed.get("doi") or _regex_doi(raw_text))
        title = parsed.get("title") or ""
        queried: List[str] = []
        responded: List[str] = []
        records: List[IndexRecord] = []

        def absorb(resp: IndexResponse) -> None:
            queried.append(resp.index)
            if resp.responded:
                responded.append(resp.index)
                records.extend(resp.records)
            else:
                logger.debug(f"  [{citation_id}] {resp.index} did not respond: {resp.error}")

        # 1. DOI is definitive when present.
        if doi:
            absorb(self.indexes.crossref_by_doi(doi))
            absorb(self.indexes.openalex_by_doi(doi))
            exact = [r for r in records if _clean_doi(r.doi) == doi]
            if exact:
                best = exact[0]
                return self._finalise(
                    citation_id, raw_text, parsed, best, 1.0,
                    ReferenceStatus.VERIFIED, queried, responded, records,
                    f"DOI {doi} resolves in {best.index}.",
                )

        # 2. Metadata search. Crossref + OpenAlex first — two discipline-agnostic
        #    indexes, which is exactly the quorum a not-found decision needs.
        query = _bibliographic_query(parsed, raw_text)
        absorb(self.indexes.crossref_bibliographic(query))
        if title:
            absorb(self.indexes.openalex_by_title(title))

        best, score = self._best_match(parsed, records)

        # 3. Escalate to the biomedical indexes only if the cheap pair missed.
        if score < REFCHECK_VERIFIED_TITLE_SIM:
            absorb(self.indexes.europepmc(query))
            ecit = _ecitmatch_fields(parsed)
            if ecit:
                absorb(self.indexes.pubmed_ecitmatch(key=citation_id, **ecit))
            elif title:
                absorb(self.indexes.pubmed_esearch(f"{title}[Title]"))
            if _is_dataish(parsed):
                absorb(self.indexes.datacite(query))
            best, score = self._best_match(parsed, records)

        # 4. Decide.
        status, explanation = self._decide(parsed, raw_text, best, score, responded)
        return self._finalise(
            citation_id, raw_text, parsed, best, score,
            status, queried, responded, records, explanation,
        )

    def _best_match(
        self, parsed: Dict[str, Any], records: List[IndexRecord]
    ) -> Tuple[Optional[IndexRecord], float]:
        """Score every candidate; return the best and its composite score."""
        parsed_title = parsed.get("title")
        parsed_year = _as_year(parsed.get("year"))
        parsed_author = parsed.get("first_author")
        parsed_journal = parsed.get("journal")

        best: Optional[IndexRecord] = None
        best_score = 0.0
        for rec in records:
            t_sim = title_similarity(parsed_title, rec.title)
            # Without a parsed title, fall back to journal+year corroboration so
            # a mangled reference is not automatically "not found".
            if not parsed_title:
                t_sim = journal_similarity(parsed_journal, rec.container)
            author_ok = _author_matches(parsed_author, rec.authors)
            year_ok = (
                parsed_year is not None and rec.year is not None
                and abs(parsed_year - rec.year) <= REFCHECK_YEAR_TOLERANCE
            )
            j_sim = journal_similarity(parsed_journal, rec.container)

            # Title dominates; corroboration can lift a borderline title match
            # over the line but can never rescue an unrelated one.
            score = t_sim + 0.04 * (1 if author_ok else 0) + 0.03 * (1 if year_ok else 0) \
                + 0.03 * j_sim
            score = min(score, 1.0)
            rec.raw["_score"] = round(score, 4)
            rec.raw["_title_sim"] = round(t_sim, 4)
            rec.raw["_author_match"] = author_ok
            rec.raw["_year_match"] = year_ok
            if score > best_score:
                best, best_score = rec, score
        return best, best_score

    def _decide(
        self,
        parsed: Dict[str, Any],
        raw_text: str,
        best: Optional[IndexRecord],
        score: float,
        responded: List[str],
    ) -> Tuple[ReferenceStatus, str]:
        distinct_responded = sorted(set(responded))
        names = ", ".join(distinct_responded) or "no index"

        if best is not None and score >= REFCHECK_VERIFIED_TITLE_SIM:
            corroborated = best.raw.get("_author_match") or best.raw.get("_year_match")
            if corroborated or not (parsed.get("first_author") or parsed.get("year")):
                return (
                    ReferenceStatus.VERIFIED,
                    f"Matched in {best.index} (title similarity {score:.2f}).",
                )
            return (
                ReferenceStatus.AMBIGUOUS,
                f"Title matches a record in {best.index} ({score:.2f}) but neither the "
                f"first author nor the year agrees — check the reference details.",
            )

        if best is not None and score >= REFCHECK_AMBIGUOUS_TITLE_SIM:
            return (
                ReferenceStatus.AMBIGUOUS,
                f"Closest record in {best.index} scores {score:.2f}, below the "
                f"{REFCHECK_VERIFIED_TITLE_SIM:.2f} confirmation threshold.",
            )

        # Below here we found nothing convincing. Everything that follows exists
        # to avoid turning that into an accusation.
        if len(set(responded)) < REFCHECK_MIN_INDEXES_FOR_NOT_FOUND:
            return (
                ReferenceStatus.UNVERIFIED,
                f"Could not check this reference: only {len(distinct_responded)} index "
                f"({names}) responded, and confirming an absence needs at least "
                f"{REFCHECK_MIN_INDEXES_FOR_NOT_FOUND}.",
            )

        unindexed_reason = _unindexed_by_design_reason(parsed, raw_text)
        if unindexed_reason:
            return (
                ReferenceStatus.UNINDEXED_BY_DESIGN,
                f"Not found in {names}, but {unindexed_reason} — this kind of reference "
                f"is not reliably carried by bibliographic indexes, so its absence is "
                f"not evidence of a problem.",
            )

        return (
            ReferenceStatus.NOT_FOUND_IN_INDEXES,
            f"Not found in {names}. This does not prove the reference does not exist — "
            f"it means these indexes returned no match. Verify the title, authors and "
            f"year against the original.",
        )

    def _finalise(
        self,
        citation_id: str,
        raw_text: str,
        parsed: Dict[str, Any],
        best: Optional[IndexRecord],
        score: float,
        status: ReferenceStatus,
        queried: List[str],
        responded: List[str],
        records: List[IndexRecord],
        explanation: str,
    ) -> ReferenceCheck:
        matched = best if status in (ReferenceStatus.VERIFIED, ReferenceStatus.AMBIGUOUS) else None
        retraction, notice = self._retraction_for(matched, records)

        near_miss = None
        if best is not None and matched is None:
            near_miss = {
                "index": best.index,
                "title": best.title,
                "year": best.year,
                "doi": best.doi,
                "score": round(score, 4),
                "url": best.url,
            }

        return ReferenceCheck(
            citation_id=citation_id,
            raw_citation_text=raw_text,
            parsed=parsed,
            status=status,
            matched_doi=_clean_doi(matched.doi) if matched else None,
            matched_title=matched.title if matched else None,
            matched_url=(
                f"https://doi.org/{_clean_doi(matched.doi)}"
                if matched and matched.doi else (matched.url if matched else None)
            ),
            match_score=round(score, 4) if best is not None else None,
            near_miss=near_miss,
            indexes_queried=sorted(set(queried)),
            indexes_responded=sorted(set(responded)),
            retraction_status=retraction,
            retraction_notice_url=notice,
            explanation=explanation,
        )

    @staticmethod
    def _retraction_for(
        matched: Optional[IndexRecord], records: List[IndexRecord]
    ) -> Tuple[RetractionStatus, Optional[str]]:
        """Retraction is asserted only from records that are the same work.

        OpenAlex's ``is_retracted`` is the primary signal; Europe PMC and PubMed
        publication types corroborate. Nothing here changes a claim verdict —
        a retracted paper can still contain the sentence being cited.
        """
        if matched is None:
            return RetractionStatus.UNKNOWN, None

        doi = _clean_doi(matched.doi)
        pmid = matched.pmid
        same_work = [
            r for r in records
            if (doi and _clean_doi(r.doi) == doi) or (pmid and r.pmid == pmid) or r is matched
        ]
        if any(r.is_retracted for r in same_work):
            notice = next(
                (r.retraction_notice_url for r in same_work if r.retraction_notice_url), None
            )
            return RetractionStatus.RETRACTED, notice
        if any(r.raw.get("_concern_raised") for r in same_work):
            return RetractionStatus.CONCERN_RAISED, None
        if any(r.is_retracted is False for r in same_work):
            return RetractionStatus.NONE, None
        return RetractionStatus.UNKNOWN, None

    # ------------------------------------------------------------------
    # Cache
    # ------------------------------------------------------------------

    def flush_cache(self) -> None:
        if not self._cache_dirty:
            return
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, ensure_ascii=False)
            self._cache_dirty = False
        except Exception as e:
            logger.debug(f"Could not write reference-check cache: {e}")


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _default_cache_path() -> Path:
    override = os.getenv("ASV_REFCHECK_CACHE")
    if override:
        return Path(override)
    return Path.home() / ".cache" / "asv" / "refcheck.json"


def _load_cache(path: Path) -> Dict[str, dict]:
    try:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}


def _cache_key(raw_text: str) -> str:
    return hashlib.sha256(normalise_title(raw_text).encode("utf-8")).hexdigest()


_DOI_RE = re.compile(r"\b(10\.\d{4,}/\S+?)(?:[,\s\])}]|$)", re.IGNORECASE)


def _regex_doi(text: str) -> Optional[str]:
    if not text:
        return None
    m = _DOI_RE.search(text)
    return m.group(1).rstrip(".") if m else None


def _clean_doi(doi: Optional[str]) -> Optional[str]:
    if not doi:
        return None
    doi = str(doi).strip().rstrip(".")
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi, flags=re.IGNORECASE)
    return doi.lower() or None


def _as_year(value: Any) -> Optional[int]:
    try:
        year = int(str(value)[:4])
    except (TypeError, ValueError):
        return None
    return year if 1400 <= year <= 2100 else None


def _author_matches(parsed_author: Optional[str], candidates: List[str]) -> bool:
    if not parsed_author or not candidates:
        return False
    target = normalise_title(parsed_author)
    if not target:
        return False
    target = target.split()[-1]
    return any(normalise_title(c).split()[-1:] == [target] for c in candidates if c)


def _bibliographic_query(parsed: Dict[str, Any], raw_fallback: str) -> str:
    """A tight query from parsed fields; the raw string is a poor query because
    it is full of journal abbreviations and page ranges."""
    if parsed.get("title"):
        parts = [str(parsed["title"])]
        if parsed.get("first_author"):
            parts.append(str(parsed["first_author"]))
        if parsed.get("year"):
            parts.append(str(parsed["year"]))
        return " ".join(parts)
    return (raw_fallback or "")[:300]


def _ecitmatch_fields(parsed: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """PubMed's citation matcher needs journal|year|volume|firstpage|author.

    Exact rather than fuzzy, so it is worth the extra parse fields
    (``academic_paper_finder`` was extended to return volume/pages for this).
    """
    journal = parsed.get("journal")
    year = _as_year(parsed.get("year"))
    volume = parsed.get("volume")
    first_page = parsed.get("first_page")
    author = parsed.get("first_author")
    if not (journal and year and volume and first_page):
        return None
    return {
        "journal": str(journal),
        "year": str(year),
        "volume": str(volume),
        "first_page": str(first_page),
        "author": str(author or ""),
    }


def _is_dataish(parsed: Dict[str, Any]) -> bool:
    t = str(parsed.get("type") or "").lower()
    return any(k in t for k in ("dataset", "data set", "software", "thesis", "dissertation"))


def _unindexed_by_design_reason(parsed: Dict[str, Any], raw_text: str) -> Optional[str]:
    """Explain an absence that is expected rather than suspicious.

    Returns a human-readable clause, or None if the absence is unexplained.
    Checked only *after* the lookup fails — many book chapters do have DOIs, so
    this classifies an absence rather than skipping the search.
    """
    declared = str(parsed.get("type") or "").strip().lower().replace("_", "-")
    if declared and declared.replace("-", "_") in UNINDEXED_REFERENCE_TYPES:
        return f"it is a {declared.replace('-', ' ')}"
    if declared in UNINDEXED_REFERENCE_TYPES:
        return f"it is a {declared}"

    if _BOOKISH_RE.search(raw_text or ""):
        return "it looks like a book, chapter, thesis or personal communication"

    year = _as_year(parsed.get("year"))
    if year is not None and year < REFCHECK_MIN_INDEXED_YEAR:
        return f"it predates {REFCHECK_MIN_INDEXED_YEAR}"

    if not parsed.get("title"):
        return "no title could be parsed from the reference string"

    return None
