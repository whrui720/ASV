"""Validation tools package.

``TruthTableChecker`` (Google Fact Check API) was removed in Tier 0.1. Its only
two call sites were the uncited-claim plausibility paths, which no longer
exist; it had near-zero coverage of academic claims and wrote
"No API key configured" into 233 user-facing explanation strings in the
measured run. See docs/TIER0_PLAN.md §3.1.
"""

from .llm_verifier import LLMVerifier
from .python_script_validator import PythonScriptValidator

__all__ = [
    'LLMVerifier',
    'PythonScriptValidator',
]
