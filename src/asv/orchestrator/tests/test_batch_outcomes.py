"""Tier 0.3 — the three-way batch outcome, and Tier 0.6 flags on batches.

"Bytes arrived" and "the bytes are evidence" are different questions. Before
Tier 0 they were one boolean, which is how nine Nature landing pages came to be
RAG-searched for evidence they could not contain.
"""

import pytest

from asv.core.models import ClaimObject
from asv.core.verdicts import (
    ContentQuality, NotCheckableReason, ReferenceStatus, RetractionStatus, Verdict,
)
from asv.core.models import ReferenceCheck
from asv.orchestrator.claim_orchestrator import ClaimOrchestrator

pytestmark = pytest.mark.unit


class RecordingEvents:
    def __init__(self):
        self.emitted = []

    def emit(self, event, **payload):
        self.emitted.append((event, payload))


def _orchestrator(reference_checks=None) -> ClaimOrchestrator:
    orc = object.__new__(ClaimOrchestrator)
    orc.events = RecordingEvents()
    orc.reference_checks = reference_checks or {}
    return orc


def _claim(claim_id="c1") -> ClaimObject:
    return ClaimObject(
        claim_id=claim_id, text="a claim", claim_type="qualitative",
        citation_found=True, citation_id="7", citation_text="[7]",
    )


def _download(**kwargs):
    base = {
        'downloaded': True, 'judgeable': True,
        'content_quality': ContentQuality.FULL_TEXT,
        'content_signals': {'usable_chars': 40000, 'imrad_count': 4},
        'path': '/tmp/x.html', 'winning_url': 'https://europepmc.org/x',
        'attempts': [{'url': 'https://europepmc.org/x'}], 'error': None,
    }
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# _batch_outcome
# ---------------------------------------------------------------------------

def test_full_text_is_judgeable():
    judgeable, quality, reason, note = _orchestrator()._batch_outcome(_download())
    assert judgeable is True
    assert quality == ContentQuality.FULL_TEXT
    assert reason is None


def test_abstract_only_is_downloaded_but_not_judgeable():
    judgeable, quality, reason, note = _orchestrator()._batch_outcome(_download(
        judgeable=False, content_quality=ContentQuality.ABSTRACT_ONLY,
        content_signals={'usable_chars': 9000, 'imrad_count': 0},
    ))
    assert judgeable is False
    assert reason == NotCheckableReason.ABSTRACT_ONLY
    assert "9000 chars" in note


def test_paywall_gets_its_own_reason():
    _, _, reason, _ = _orchestrator()._batch_outcome(_download(
        judgeable=False, content_quality=ContentQuality.PAYWALL_INTERSTITIAL,
    ))
    assert reason == NotCheckableReason.PAYWALL_INTERSTITIAL


def test_no_candidates_and_failed_fetch_are_distinguished():
    """"We never found a URL" and "we found one and it 403ed" imply different
    user actions — retry with a login vs fix the reference."""
    orc = _orchestrator()
    _, _, no_url, _ = orc._batch_outcome(
        {'downloaded': False, 'attempts': [], 'error': 'no URL'}
    )
    _, _, failed, _ = orc._batch_outcome(
        {'downloaded': False, 'attempts': [{'url': 'x'}], 'error': '403'}
    )
    assert no_url == NotCheckableReason.SOURCE_NOT_RESOLVED
    assert failed == NotCheckableReason.SOURCE_DOWNLOAD_FAILED


def test_string_content_quality_is_coerced():
    """Results round-tripped through JSON carry the enum's value, not the enum."""
    _, quality, _, _ = _orchestrator()._batch_outcome(_download(
        content_quality="abstract_only", judgeable=False,
    ))
    assert quality == ContentQuality.ABSTRACT_ONLY


# ---------------------------------------------------------------------------
# _abstain_batch
# ---------------------------------------------------------------------------

def test_abstain_batch_marks_every_claim_not_checkable():
    orc = _orchestrator()
    claims = [_claim("c1"), _claim("c2")]
    batch = orc._abstain_batch(
        "7", claims[0], claims, NotCheckableReason.ABSTRACT_ONLY, "abstract only",
        attempts=[], download_result=_download(judgeable=False), method="rag_search",
        quality=ContentQuality.ABSTRACT_ONLY,
    )
    assert batch.judgeable is False
    assert batch.content_quality == ContentQuality.ABSTRACT_ONLY
    assert len(batch.claim_results) == 2
    for r in batch.claim_results:
        assert r.verdict == Verdict.NOT_CHECKABLE
        assert r.not_checkable_reason == NotCheckableReason.ABSTRACT_ONLY
        assert r.confidence is None
        assert r.content_quality == ContentQuality.ABSTRACT_ONLY


def test_abstract_only_explanation_states_the_policy():
    orc = _orchestrator()
    batch = orc._abstain_batch(
        "7", _claim(), [_claim()], NotCheckableReason.ABSTRACT_ONLY, "note",
        attempts=[], download_result=_download(judgeable=False), method="rag_search",
        quality=ContentQuality.ABSTRACT_ONLY,
    )
    text = batch.claim_results[0].explanation.lower()
    assert "abstract" in text
    assert "full text" in text


def test_download_failure_explanation_does_not_blame_the_claim():
    """This was previously `passed: false, confidence 0.0`, which reads as "this
    claim is wrong" when it means "we never checked it"."""
    orc = _orchestrator()
    batch = orc._abstain_batch(
        "7", _claim(), [_claim()], NotCheckableReason.SOURCE_DOWNLOAD_FAILED, "note",
        attempts=[], download_result={'downloaded': False, 'attempts': [{'url': 'x'}]},
        method="rag_search", quality=None,
    )
    assert "says nothing about whether the claim is correct" in \
        batch.claim_results[0].explanation


# ---------------------------------------------------------------------------
# Tier 0.6 flags ride along, orthogonally
# ---------------------------------------------------------------------------

def _check(status=ReferenceStatus.VERIFIED, retraction=RetractionStatus.NONE):
    return ReferenceCheck(
        citation_id="7", raw_citation_text="ref", status=status,
        retraction_status=retraction,
    )


def test_retracted_source_raises_a_flag_not_a_verdict():
    """A retracted paper can still literally contain the sentence being cited,
    so retraction is a flag on the finding, never the finding itself."""
    orc = _orchestrator({"7": _check(retraction=RetractionStatus.RETRACTED)})
    assert orc._reference_flags("7") == ["cited_source_retracted"]


def test_expression_of_concern_has_its_own_flag():
    orc = _orchestrator({"7": _check(retraction=RetractionStatus.CONCERN_RAISED)})
    assert orc._reference_flags("7") == ["cited_source_concern_raised"]


def test_unindexed_reference_is_flagged():
    orc = _orchestrator({"7": _check(status=ReferenceStatus.NOT_FOUND_IN_INDEXES)})
    assert "reference_unindexed" in orc._reference_flags("7")


def test_clean_reference_raises_no_flags():
    orc = _orchestrator({"7": _check()})
    assert orc._reference_flags("7") == []


def test_unknown_citation_raises_no_flags():
    assert _orchestrator()._reference_flags("999") == []


def test_reference_check_is_attached_to_the_batch():
    check = _check(retraction=RetractionStatus.RETRACTED)
    orc = _orchestrator({"7": check})
    batch = orc._abstain_batch(
        "7", _claim(), [_claim()], NotCheckableReason.SOURCE_DOWNLOAD_FAILED, "note",
        attempts=[], download_result={'downloaded': False, 'attempts': []},
        method="rag_search", quality=None,
    )
    assert batch.reference_check is check
    assert "cited_source_retracted" in batch.claim_results[0].flags
