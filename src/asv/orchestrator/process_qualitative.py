"""Process Qualitative - Orchestration logic for qualitative claim processing"""

import logging
from typing import Optional

from asv.core.models import ClaimObject, ValidationResult, not_checkable
from asv.core.verdicts import ContentQuality, NotCheckableReason, Verdict
from asv.extraction.llm_client import LLMClient
from asv.validator.llm_verifier import LLMVerifier

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ProcessQualitative:
    """Orchestrate qualitative claim processing using validator tools"""

    def __init__(self, llm_client: LLMClient):
        self.llm_tool = LLMVerifier(llm_client)

    def validate_claim(
        self,
        claim: ClaimObject,
        source_text: str,
        source_url: Optional[str] = None,
        content_quality: Optional[ContentQuality] = None,
        source_fetched_at: Optional[str] = None,
    ) -> ValidationResult:
        """Verify one claim against retrieved source text.

        ``source_text`` is **required and must be non-empty**. Tier 0.1 removed
        the "no source? fall back to a plausibility check" branch that used to
        live here. It was unreachable in practice — both cited paths already
        skip batches whose download failed — but it directly contradicted the
        invariant CLAUDE.md advertises to readers ("an empty/paywalled source
        cannot produce a fake ``llm_check`` pass"), and dead code that
        contradicts a documented invariant is one refactor away from firing.
        Making the parameter required is what stops it coming back.
        """
        logger.info(f"Processing claim: {claim.claim_id}")

        if not source_text or not source_text.strip():
            # Defensive: callers are supposed to have gated on this already.
            return not_checkable(
                claim,
                NotCheckableReason.SOURCE_DOWNLOAD_FAILED,
                "No source text was available to check this claim against.",
                source_url=source_url,
                content_quality=content_quality,
            )

        try:
            verification = self.llm_tool.verify_claim_against_source(
                claim.text, source_text, source_url=source_url,
            )
        except Exception as e:
            logger.error(f"Verification error for {claim.claim_id}: {e}")
            return not_checkable(
                claim,
                NotCheckableReason.VALIDATION_ERROR,
                "Verification failed with an internal error.",
                errors=str(e),
                source_url=source_url,
                content_quality=content_quality,
            )

        metadata = dict(verification.get("metadata") or {})
        # B3: retrieved chunks + similarity scores for the evidence pane.
        metadata["rag_chunks"] = verification.get("rag_chunks", [])

        verdict: Verdict = verification["verdict"]
        if verdict == Verdict.NOT_CHECKABLE:
            return not_checkable(
                claim,
                verification["not_checkable_reason"],
                verification["explanation"],
                method="rag_search",
                errors=verification.get("error"),
                source_url=source_url,
                content_quality=content_quality,
                validation_metadata=metadata,
            )

        evidence = verification["evidence"]
        return ValidationResult(
            claim_id=claim.claim_id,
            claim_type=claim.claim_type,
            originally_uncited=claim.originally_uncited,
            verdict=verdict,
            not_checkable_reason=None,
            validated=True,
            validation_method="rag_search",
            confidence=verification.get("confidence"),
            explanation=verification["explanation"],
            evidence=evidence,
            source_url=source_url,
            source_fetched_at=source_fetched_at,
            content_quality=content_quality,
            flags=(["claimed_original"] if claim.is_original else []),
            sources_used=[source_url] if source_url else [],
            errors=verification.get("error"),
            validation_metadata=metadata,
        )
