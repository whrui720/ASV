"""The Tier 0.2/0.5 contract, enforced at construction.

VALUE_PROPOSITION.md §0 diagnoses ASV's central defect as a *data-shape*
problem: the result model could represent "confident verdict, no evidence", and
so the pipeline produced 224 of those. A convention prevents that until the next
contributor. These tests pin the invariant that makes the state unrepresentable.
"""

import pytest
from pydantic import ValidationError

from asv.core.models import (
    ClaimObject, EvidenceSpan, ValidationResult, not_checkable,
)
from asv.core.verdicts import (
    ACCUSATION_VERDICTS, EVIDENCED_VERDICTS, NotCheckableReason, Verdict,
)

pytestmark = pytest.mark.unit


BASE = dict(
    claim_id="c1",
    claim_type="qualitative",
    originally_uncited=False,
    validated=True,
    validation_method="rag_search",
    explanation="explanation",
)


def _span(verified: bool = True) -> EvidenceSpan:
    return EvidenceSpan(
        quote="the virus replicates in epithelial cells",
        source_url="https://doi.org/10.1234/example",
        verified_verbatim=verified,
    )


def _claim(**kwargs) -> ClaimObject:
    return ClaimObject(**{
        "claim_id": "c1", "text": "a claim", "claim_type": "qualitative",
        "citation_found": False, **kwargs,
    })


# ---------------------------------------------------------------------------
# Tier 0.5 — no judgment without evidence
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("verdict", sorted(EVIDENCED_VERDICTS, key=lambda v: v.value))
def test_judgment_requires_evidence(verdict):
    with pytest.raises(ValidationError, match="EvidenceSpan"):
        ValidationResult(
            verdict=verdict, confidence=0.9,
            source_url="https://doi.org/10.1234/example", **BASE,
        )


@pytest.mark.parametrize("verdict", sorted(EVIDENCED_VERDICTS, key=lambda v: v.value))
def test_judgment_requires_a_verbatim_verified_span(verdict):
    """An unverified quote is worse than none: it looks checkable and is not."""
    with pytest.raises(ValidationError, match="verbatim-verified"):
        ValidationResult(
            verdict=verdict, confidence=0.9,
            source_url="https://doi.org/10.1234/example",
            evidence=[_span(verified=False)], **BASE,
        )


@pytest.mark.parametrize("verdict", sorted(EVIDENCED_VERDICTS, key=lambda v: v.value))
def test_judgment_requires_a_source_url(verdict):
    with pytest.raises(ValidationError, match="source_url"):
        ValidationResult(
            verdict=verdict, confidence=0.9, evidence=[_span()], **BASE,
        )


def test_well_formed_judgment_is_accepted():
    result = ValidationResult(
        verdict=Verdict.SUBSTANTIATED, confidence=0.9,
        source_url="https://doi.org/10.1234/example",
        evidence=[_span()], **BASE,
    )
    assert result.verdict == Verdict.SUBSTANTIATED
    assert result.evidence[0].verified_verbatim


def test_accusation_verdicts_also_require_evidence():
    """"Not substantiated" is an allegation, and VALUE_PROPOSITION.md §10 rates
    false accusation the critical risk. The honest evidence for it is the
    passage that came closest and still does not say this."""
    for verdict in ACCUSATION_VERDICTS:
        with pytest.raises(ValidationError):
            ValidationResult(
                verdict=verdict, confidence=0.4,
                source_url="https://doi.org/10.1234/example", **BASE,
            )
        ok = ValidationResult(
            verdict=verdict, confidence=0.4,
            source_url="https://doi.org/10.1234/example",
            evidence=[EvidenceSpan(
                quote="the study examined murine models only",
                role="nearest_relevant",
                source_url="https://doi.org/10.1234/example",
                verified_verbatim=True,
            )],
            **BASE,
        )
        assert ok.evidence[0].role == "nearest_relevant"


# ---------------------------------------------------------------------------
# Tier 0.2 — abstentions carry a reason, never a number
# ---------------------------------------------------------------------------

def test_abstention_requires_a_reason_code():
    with pytest.raises(ValidationError, match="reason code"):
        ValidationResult(verdict=Verdict.NOT_CHECKABLE, **{**BASE, "validated": False})


def test_abstention_must_not_carry_a_confidence():
    with pytest.raises(ValidationError, match="confidence"):
        ValidationResult(
            verdict=Verdict.NOT_CHECKABLE,
            not_checkable_reason=NotCheckableReason.ABSTRACT_ONLY,
            confidence=0.5, **{**BASE, "validated": False},
        )


def test_reason_code_rejected_on_a_judgment():
    with pytest.raises(ValidationError, match="not_checkable_reason"):
        ValidationResult(
            verdict=Verdict.SUBSTANTIATED,
            not_checkable_reason=NotCheckableReason.ABSTRACT_ONLY,
            confidence=0.9, source_url="https://x", evidence=[_span()], **BASE,
        )


@pytest.mark.parametrize("reason", list(NotCheckableReason))
def test_every_reason_code_constructs(reason):
    result = not_checkable(_claim(), reason, "because")
    assert result.verdict == Verdict.NOT_CHECKABLE
    assert result.not_checkable_reason == reason
    assert result.confidence is None
    assert result.validated is False


# ---------------------------------------------------------------------------
# `passed` — derived, deprecated, and deliberately conservative
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("verdict,expected", [
    (Verdict.SUBSTANTIATED, True),
    (Verdict.PARTIALLY_SUBSTANTIATED, False),
    (Verdict.NOT_SUBSTANTIATED, False),
    (Verdict.CONTRADICTED, False),
])
def test_passed_is_derived_conservatively(verdict, expected):
    """A legacy consumer filtering `passed == true` must under-count rather than
    over-count: for a tool whose failure mode is unearned confidence, that is
    the only acceptable direction to be wrong in."""
    result = ValidationResult(
        verdict=verdict, confidence=0.8, source_url="https://x",
        evidence=[_span()], **BASE,
    )
    assert result.passed is expected


def test_passed_cannot_be_set_independently_of_verdict():
    """The original defect was a `passed` set independently of the evidence.
    As a computed field it cannot disagree with `verdict` — an incoming
    `passed=True` from legacy JSON is ignored, not honoured."""
    result = ValidationResult(
        verdict=Verdict.NOT_CHECKABLE,
        not_checkable_reason=NotCheckableReason.NO_SOURCE_AVAILABLE,
        passed=True, **{**BASE, "validated": False},
    )
    assert result.passed is False


def test_passed_survives_serialisation_for_legacy_consumers():
    result = not_checkable(_claim(), NotCheckableReason.NO_SOURCE_AVAILABLE, "x")
    dumped = result.model_dump(mode="json")
    assert dumped["passed"] is False
    assert dumped["verdict"] == "not_checkable"
    assert dumped["confidence"] is None


# ---------------------------------------------------------------------------
# The abstention helper
# ---------------------------------------------------------------------------

def test_original_claims_are_flagged_not_scored():
    """VALUE_PROPOSITION.md §2.4(b): a validator whose confidence tracks
    conformity-to-consensus scores novelty lowest. Original claims get their own
    abstention reason and a non-authoritative flag — never a score."""
    claim = _claim(is_original=True)
    result = not_checkable(
        claim, NotCheckableReason.ORIGINAL_CONTRIBUTION, "own contribution",
    )
    assert "claimed_original" in result.flags
    assert result.confidence is None
