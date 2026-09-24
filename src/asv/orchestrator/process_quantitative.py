"""Process Quantitative - Orchestration logic for quantitative claim processing"""

import logging
from typing import Optional

from asv.core.models import ClaimObject, EvidenceSpan, ValidationResult, not_checkable
from asv.core.verdicts import NotCheckableReason, Verdict
from asv.core.run_paths import RunPaths
from asv.extraction.llm_client import LLMClient
from asv.validator.python_script_validator import PythonScriptValidator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ProcessQuantitative:
    """Orchestrate quantitative claim processing using validator tools.

    Note: VALUE_PROPOSITION.md Tier 4 marks this whole path for removal —
    LLM-written pandas scripts hallucinate columns, run against non-datasets,
    and execute unsandboxed. Tier 0 does not cut it (that would mix two
    decisions in one change) but does hold it to the same evidence rule as
    every other path: no verdict without something a human can check.
    """

    def __init__(self, llm_client: LLMClient, run_paths: Optional[RunPaths] = None):
        self.script_tool = PythonScriptValidator(llm_client, run_paths=run_paths)
        self._run_paths = run_paths

    def validate_claim(
        self,
        claim: ClaimObject,
        dataset_path: str,
        source_url: Optional[str] = None,
        source_fetched_at: Optional[str] = None,
    ) -> ValidationResult:
        """Process a quantitative claim using the Python script validation tool."""
        logger.info(f"Processing quantitative claim: {claim.claim_id}")

        result = self.script_tool.validate(claim.text, dataset_path, claim.claim_id)

        if not result.get('validated'):
            return not_checkable(
                claim,
                NotCheckableReason.VALIDATION_ERROR,
                result.get('explanation') or "The generated validation script did not run.",
                method="python_script",
                errors=result.get('error'),
                source_url=source_url or dataset_path,
            )

        raw_output = (result.get('raw_output') or "").strip()
        if not raw_output:
            # No computed output means nothing to show a human. Abstain rather
            # than assert a result backed only by the script's say-so.
            return not_checkable(
                claim,
                NotCheckableReason.EVIDENCE_UNVERIFIABLE,
                "The validation script ran but produced no inspectable result to "
                "support a verdict.",
                method="python_script",
                errors=result.get('error'),
                source_url=source_url or dataset_path,
            )

        locator = None
        if self._run_paths is not None:
            locator = f"generated_scripts/validate_{claim.claim_id}.py"

        evidence = [EvidenceSpan(
            quote=raw_output[:2000],
            role="supporting" if result.get('passed') else "nearest_relevant",
            source_url=source_url or dataset_path,
            locator=locator,
            # Captured verbatim from the executed script's stdout: deterministic
            # and reproducible by re-running the script stored next to it.
            verified_verbatim=True,
        )]

        return ValidationResult(
            claim_id=claim.claim_id,
            claim_type=claim.claim_type,
            originally_uncited=claim.originally_uncited,
            verdict=Verdict.SUBSTANTIATED if result['passed'] else Verdict.NOT_SUBSTANTIATED,
            validated=True,
            validation_method="python_script",
            confidence=result.get('confidence'),
            explanation=result['explanation'],
            evidence=evidence,
            source_url=source_url or dataset_path,
            source_fetched_at=source_fetched_at,
            flags=(["claimed_original"] if claim.is_original else []),
            sources_used=[source_url] if source_url else [],
            errors=result.get('error'),
            validation_metadata={"dataset_path": dataset_path},
        )
