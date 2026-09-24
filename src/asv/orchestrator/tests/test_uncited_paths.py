"""Tier 0.1 — the plausibility verdict is gone, not merely unused.

On the reference run this path produced **217 of 224 passes** with
``sources_used: []`` — 81% of all output, none of it backed by anything. It
also inverted the project's own thesis twice: it manufactured exactly the
confident-looking unsupported number ASV exists to catch, and because a novel
finding is by definition absent from a model's priors, it scored originality
lowest and platitudes highest.

These tests pin both halves: the right output shape, and the absence of the
model call that used to produce the wrong one.
"""

import pytest

from asv.core.models import ClaimObject
from asv.core.verdicts import NotCheckableReason, Verdict
from asv.orchestrator.claim_orchestrator import ClaimOrchestrator

pytestmark = pytest.mark.unit


class RecordingEvents:
    def __init__(self):
        self.emitted = []

    def emit(self, event, **payload):
        self.emitted.append((event, payload))


class ForbiddenLLM:
    """Any call through this is a test failure: the uncited path must not use a
    model at all."""

    def call_llm(self, *args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("the uncited path must not call an LLM")


def _orchestrator(**attrs) -> ClaimOrchestrator:
    """Build an orchestrator without __init__ (which opens a browser, a log
    file and an API client) and inject only what the method under test uses."""
    orc = object.__new__(ClaimOrchestrator)
    orc.events = RecordingEvents()
    orc.llm_client = ForbiddenLLM()
    orc.reference_checks = {}
    for k, v in attrs.items():
        setattr(orc, k, v)
    return orc


def _claim(claim_id="c1", **kwargs) -> ClaimObject:
    return ClaimObject(**{
        "claim_id": claim_id, "text": "HSV-1 is a neurotropic DNA virus.",
        "claim_type": "qualitative", "citation_found": False, **kwargs,
    })


# ---------------------------------------------------------------------------
# Output shape
# ---------------------------------------------------------------------------

def test_uncited_claims_are_not_checkable():
    orc = _orchestrator()
    results = orc._process_uncited_qualitative([_claim("c1"), _claim("c2")])

    assert len(results) == 2
    for r in results:
        assert r.verdict == Verdict.NOT_CHECKABLE
        assert r.not_checkable_reason == NotCheckableReason.NO_SOURCE_AVAILABLE
        assert r.confidence is None
        assert r.passed is False
        assert r.validated is False
        assert r.evidence == []
        assert r.sources_used == []


def test_explanation_says_what_was_and_was_not_done():
    orc = _orchestrator()
    (result,) = orc._process_uncited_qualitative([_claim()])
    assert "no citation" in result.explanation.lower()
    assert "priors" in result.explanation.lower()


def test_original_claims_get_their_own_reason_code():
    """VALUE_PROPOSITION.md §2.4(b): 25 claims were tagged original and 22
    "passed" the plausibility check. "The paper's own novel finding" and "we
    could not find the source" are different things a reviewer wants separated."""
    orc = _orchestrator()
    (result,) = orc._process_uncited_qualitative([_claim(is_original=True)])

    assert result.not_checkable_reason == NotCheckableReason.ORIGINAL_CONTRIBUTION
    assert "claimed_original" in result.flags
    assert result.confidence is None


def test_original_claim_wording_is_not_authoritative():
    """The is_original classifier misfires badly on review papers, so the copy
    must attribute the claim to the paper, never assert it as fact."""
    orc = _orchestrator()
    (result,) = orc._process_uncited_qualitative([_claim(is_original=True)])
    assert "presents this as its own" in result.explanation


# ---------------------------------------------------------------------------
# The absence of the model call
# ---------------------------------------------------------------------------

def test_no_llm_call_is_made():
    """ForbiddenLLM raises on use; 247 of these per run was the bulk of the
    LLM spend, for output that could never enter a verdict."""
    orc = _orchestrator()
    orc._process_uncited_qualitative([_claim(f"c{i}") for i in range(20)])


def test_truth_table_checker_is_gone():
    """Its only two call sites were the uncited paths. A module with no callers
    that holds an API key and makes network calls is a liability, and it wrote
    "No API key configured" into 233 user-facing strings."""
    assert not hasattr(ClaimOrchestrator, "truth_table")
    with pytest.raises(ImportError):
        from asv.validator.truth_table_checker import TruthTableChecker  # noqa: F401

    import asv.validator as validator
    assert "TruthTableChecker" not in validator.__all__


def test_plausibility_primitive_is_gone():
    """Deleting the callers while keeping the primitive guarantees it returns."""
    from asv.validator.llm_verifier import LLMVerifier
    assert not hasattr(LLMVerifier, "verify_claim")
    assert not hasattr(LLMVerifier, "_build_verification_prompt")


def test_qualitative_processor_requires_source_text():
    """The old "no source? fall back to plausibility" branch is removed, and the
    parameter is required so it cannot be silently reintroduced."""
    import inspect
    from asv.orchestrator.process_qualitative import ProcessQualitative

    sig = inspect.signature(ProcessQualitative.validate_claim)
    assert sig.parameters["source_text"].default is inspect.Parameter.empty


def test_events_report_verdicts_not_booleans():
    orc = _orchestrator()
    orc._process_uncited_qualitative([_claim()])
    event, payload = orc.events.emitted[0]
    assert event == "claim_validated"
    assert payload["verdict"] == "not_checkable"
    assert payload["reason"] == "no_source_available"
    assert "passed" not in payload
    assert "confidence" not in payload
