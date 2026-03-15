"""Process Qualitative - Orchestration logic for qualitative claim processing"""

import logging
from hybrid_citation_scraper.llm_client import LLMClient
from models import ClaimObject, ValidationResult
from validator.llm_verifier import LLMVerifier

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ProcessQualitative:
    """Orchestrate qualitative claim processing using validator tools"""

    def __init__(self, llm_client: LLMClient):
        self.llm_tool = LLMVerifier(llm_client)

    def validate_claim(self, claim: ClaimObject, source_text: str | None = None) -> ValidationResult:
        """
        Process a qualitative claim.
        - If source text exists, run source-grounded verification (RAG + LLM tool)
        - Otherwise, fall back to plain plausibility check (existing LLM tool behavior)
        """
        logger.info(f"Processing qualitative claim: {claim.claim_id}")

        try:
            if source_text and source_text.strip():
                verification = self.llm_tool.verify_claim_against_source(claim.text, source_text)

                return ValidationResult(
                    claim_id=claim.claim_id,
                    claim_type=claim.claim_type,
                    originally_uncited=claim.originally_uncited,
                    validated=verification.get('error') is None,
                    validation_method="rag_search",
                    confidence=verification['confidence'],
                    passed=verification['passed'],
                    explanation=verification['explanation'],
                    sources_used=verification.get('supporting_quotes', []),
                    errors=verification.get('error')
                )

            # Fallback path requested by user: use non-RAG plausibility check when no source
            plausibility = self.llm_tool.verify_claim(claim.text)
            return ValidationResult(
                claim_id=claim.claim_id,
                claim_type=claim.claim_type,
                originally_uncited=claim.originally_uncited,
                validated=True,
                validation_method="llm_check",
                confidence=plausibility['confidence'],
                passed=plausibility['plausible'],
                explanation=plausibility['reasoning'],
                sources_used=[],
                errors=None
            )

        except Exception as e:
            logger.error(f"Qualitative processing error: {str(e)}")
            return ValidationResult(
                claim_id=claim.claim_id,
                claim_type=claim.claim_type,
                originally_uncited=claim.originally_uncited,
                validated=False,
                validation_method="rag_search",
                confidence=0.0,
                passed=False,
                explanation="Validation error occurred",
                sources_used=[],
                errors=str(e)
            )