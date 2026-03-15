"""Process Quantitative - Orchestration logic for quantitative claim processing"""

import logging
from hybrid_citation_scraper.llm_client import LLMClient
from models import ClaimObject, ValidationResult
from validator.python_script_validator import PythonScriptValidator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ProcessQuantitative:
    """Orchestrate quantitative claim processing using validator tools"""

    def __init__(self, llm_client: LLMClient):
        self.script_tool = PythonScriptValidator(llm_client)

    def validate_claim(self, claim: ClaimObject, dataset_path: str) -> ValidationResult:
        """Process a quantitative claim using the Python script validation tool."""
        logger.info(f"Processing quantitative claim: {claim.claim_id}")

        result = self.script_tool.validate(claim.text, dataset_path, claim.claim_id)
        return ValidationResult(
            claim_id=claim.claim_id,
            claim_type=claim.claim_type,
            originally_uncited=claim.originally_uncited,
            validated=result['validated'],
            validation_method="python_script",
            confidence=result['confidence'],
            passed=result['passed'],
            explanation=result['explanation'],
            sources_used=[dataset_path],
            errors=result['error']
        )