"""Tier 0.5 — quotes are checked against the source before a verdict ships.

An LLM can fabricate a quote, and this system has form: VALUE_PROPOSITION.md
§2.4(c) records it inventing pandas column names that did not exist. A verdict
whose quote is not really in the source destroys the one property Tier 0.5 is
for — that a human can check the finding in ten seconds.
"""

import pytest

from asv.core.verdicts import NotCheckableReason, Verdict
from asv.validator.llm_verifier import LLMVerifier

pytestmark = pytest.mark.unit


SOURCE = """
Introduction

Herpes simplex virus type 1 establishes latency in sensory neurons.

Materials and Methods

Vero cells were infected at a multiplicity of infection of 5.

Results

Viral titres peaked at 24 hours post-infection, reaching 6.2 log10 PFU/ml.
The transition from attached to penetrated virus occurred within 10 minutes.

Discussion

These findings are consistent with earlier reports in murine models.
"""


class FakeLLM:
    """Stands in for LLMClient; records the prompt and returns a canned reply."""

    def __init__(self, response):
        self.response = response
        self.calls = []

    def call_llm(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


#: A claim with real vocabulary overlap with SOURCE, so TF-IDF retrieval
#: actually returns chunks and the test exercises quote verification rather
#: than the retrieval-empty branch.
CLAIM = "Viral titres peaked at 24 hours post-infection, reaching 6.2 log10 PFU/ml."


def _verifier(response):
    return LLMVerifier(FakeLLM(response))


# ---------------------------------------------------------------------------
# Verification succeeds
# ---------------------------------------------------------------------------

def test_verbatim_quote_is_accepted_and_located():
    v = _verifier({
        "verdict": "substantiated",
        "confidence": 0.88,
        "explanation": "The source reports the peak titre directly.",
        "quotes": [{
            "text": "Viral titres peaked at 24 hours post-infection",
            "role": "supporting",
        }],
    })
    out = v.verify_claim_against_source(
        "Viral titres peaked at 24 hours post-infection.",
        SOURCE, source_url="https://doi.org/10.1234/x",
    )
    assert out["verdict"] == Verdict.SUBSTANTIATED
    span = out["evidence"][0]
    assert span.verified_verbatim
    assert span.char_start is not None and span.char_end is not None
    # Offsets must map back into the *original* text, punctuation and all.
    assert "titres peaked" in SOURCE[span.char_start:span.char_end]


def test_quote_matches_through_pdf_extraction_noise():
    """Smart quotes, ligatures and collapsed whitespace are what PDF extraction
    produces; no model reproduces them faithfully, so matching is normalised."""
    v = _verifier({
        "verdict": "substantiated",
        "confidence": 0.8,
        "explanation": "stated directly",
        "quotes": [{
            "text": "viral   titres   PEAKED at 24 hours, post-infection!",
            "role": "supporting",
        }],
    })
    out = v.verify_claim_against_source(CLAIM, SOURCE, source_url="https://x")
    assert out["verdict"] == Verdict.SUBSTANTIATED
    assert out["evidence"][0].verified_verbatim


def test_contradicted_verdict_keeps_its_role():
    v = _verifier({
        "verdict": "contradicted",
        "confidence": 0.7,
        "explanation": "The source says murine, the claim says human.",
        "quotes": [{
            "text": "consistent with earlier reports in murine models",
            "role": "contradicting",
        }],
    })
    out = v.verify_claim_against_source(CLAIM, SOURCE, source_url="https://x")
    assert out["verdict"] == Verdict.CONTRADICTED
    assert out["evidence"][0].role == "contradicting"


# ---------------------------------------------------------------------------
# Verification fails -> abstain, never ship the verdict
# ---------------------------------------------------------------------------

def test_fabricated_quote_downgrades_to_abstention():
    v = _verifier({
        "verdict": "substantiated",
        "confidence": 0.95,
        "explanation": "It says so plainly.",
        "quotes": [{
            "text": "titres peaked at 48 hours in human hepatocyte cultures",
            "role": "supporting",
        }],
    })
    out = v.verify_claim_against_source(CLAIM, SOURCE, source_url="https://x")
    assert out["verdict"] == Verdict.NOT_CHECKABLE
    assert out["not_checkable_reason"] == NotCheckableReason.EVIDENCE_UNVERIFIABLE
    assert out["confidence"] is None
    assert out["metadata"]["unverified_quotes"]


def test_verdict_with_no_quotes_at_all_abstains():
    v = _verifier({
        "verdict": "not_substantiated",
        "confidence": 0.3,
        "explanation": "Nothing relevant.",
        "quotes": [],
    })
    out = v.verify_claim_against_source(CLAIM, SOURCE, source_url="https://x")
    assert out["verdict"] == Verdict.NOT_CHECKABLE
    assert out["not_checkable_reason"] == NotCheckableReason.EVIDENCE_UNVERIFIABLE


def test_trivially_short_quote_is_not_accepted_as_evidence():
    """A three-word "quote" matches almost any document — it is not evidence."""
    v = _verifier({
        "verdict": "substantiated", "confidence": 0.9, "explanation": "y",
        "quotes": [{"text": "the virus", "role": "supporting"}],
    })
    out = v.verify_claim_against_source(CLAIM, SOURCE, source_url="https://x")
    assert out["verdict"] == Verdict.NOT_CHECKABLE


def test_unrecognised_verdict_token_abstains():
    v = _verifier({
        "verdict": "probably fine", "confidence": 0.9, "explanation": "y",
        "quotes": [{"text": "Viral titres peaked at 24 hours post-infection", "role": "supporting"}],
    })
    out = v.verify_claim_against_source(CLAIM, SOURCE, source_url="https://x")
    assert out["verdict"] == Verdict.NOT_CHECKABLE
    assert out["not_checkable_reason"] == NotCheckableReason.VALIDATION_ERROR


def test_llm_failure_abstains_rather_than_failing_the_claim():
    v = _verifier(RuntimeError("503 UNAVAILABLE"))
    out = v.verify_claim_against_source(CLAIM, SOURCE, source_url="https://x")
    assert out["verdict"] == Verdict.NOT_CHECKABLE
    assert out["not_checkable_reason"] == NotCheckableReason.VALIDATION_ERROR


# ---------------------------------------------------------------------------
# Retrieval failure is not claim failure (Tier 2.4, forced early by Tier 0.5)
# ---------------------------------------------------------------------------

def test_empty_retrieval_is_an_abstention_not_a_failed_claim():
    """This hit 12 of 22 successfully-downloaded claims in the reference run and
    was reported as a failed claim. It is a retrieval failure. With Tier 0.5
    there is no span to attach, so the old state is unconstructible."""
    v = _verifier({"verdict": "substantiated", "confidence": 1.0, "explanation": "", "quotes": []})
    out = v.verify_claim_against_source(
        "zzzz qqqq xxxx unrelated vocabulary entirely",
        "Completely different subject matter about medieval agriculture and crop rotation "
        "systems in northern Europe during the fourteenth century, at some length.",
        source_url="https://x",
    )
    assert out["verdict"] == Verdict.NOT_CHECKABLE
    assert out["not_checkable_reason"] == NotCheckableReason.RETRIEVAL_EMPTY
    assert out["evidence"] == []


def test_empty_source_abstains():
    v = _verifier({})
    out = v.verify_claim_against_source(CLAIM, "   ", source_url="https://x")
    assert out["verdict"] == Verdict.NOT_CHECKABLE
    assert out["not_checkable_reason"] == NotCheckableReason.RETRIEVAL_EMPTY


def test_no_llm_call_is_made_when_retrieval_is_empty():
    """Cost: a batch whose retrieval finds nothing should not pay for a model
    call to be told so."""
    fake = FakeLLM({})
    v = LLMVerifier(fake)
    v.verify_claim_against_source("zzzz qqqq", "", source_url="https://x")
    assert fake.calls == []


# ---------------------------------------------------------------------------
# Prompt contract (R10)
# ---------------------------------------------------------------------------

def test_prompt_asks_for_graded_verdicts_and_verbatim_quotes():
    fake = FakeLLM({
        "verdict": "substantiated", "confidence": 0.9, "explanation": "y",
        "quotes": [{"text": "Viral titres peaked at 24 hours post-infection", "role": "supporting"}],
    })
    LLMVerifier(fake).verify_claim_against_source(
        "Viral titres peaked at 24 hours.", SOURCE, source_url="https://x",
    )
    prompt, kwargs = fake.calls[0]
    for token in (
        "partially_substantiated", "contradicted", "not_substantiated",
        "verbatim", "nearest_relevant",
    ):
        assert token in prompt
    assert kwargs["task_name"] == "source_grounded_verification"
