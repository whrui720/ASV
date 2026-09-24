"""The run summary must survive — and report — an all-abstention run.

Two things changed under Tier 0 that this file guards:

1. ``confidence`` became optional, so the old
   ``sum(confidences) / len(confidences)`` raises ``TypeError`` the moment a
   run contains an abstention. After Tier 0.1 that is every run.
2. ``pass_rate`` divided by passed+failed, which on the reference run put 217
   unsourced plausibility passes in the numerator and reported 73%. The
   replacement is computed over claims that could actually be checked.
"""

import json

import pytest

from asv.core.models import (
    ClaimObject, EvidenceSpan, ReferenceCheck, ValidationBatch, ValidationResult,
    not_checkable,
)
from asv.core.run_paths import RunPaths
from asv.core.verdicts import (
    NotCheckableReason, ReferenceStatus, RetractionStatus, Verdict,
)
from asv.orchestrator.claim_orchestrator import ClaimOrchestrator

pytestmark = pytest.mark.unit


class FakeCostClient:
    def get_cost_summary(self):
        return {"input_tokens": 10, "output_tokens": 5, "total_cost": 0.001}


def _claim(claim_id, cited=False, quantitative=False) -> ClaimObject:
    return ClaimObject(
        claim_id=claim_id, text="a claim",
        claim_type="quantitative" if quantitative else "qualitative",
        citation_found=cited,
        citation_id="7" if cited else None,
    )


def _judgment(claim_id, verdict=Verdict.SUBSTANTIATED, confidence=0.9) -> ValidationResult:
    return ValidationResult(
        claim_id=claim_id, claim_type="qualitative", originally_uncited=False,
        verdict=verdict, validated=True, validation_method="rag_search",
        confidence=confidence, explanation="because",
        source_url="https://doi.org/10.1/x",
        evidence=[EvidenceSpan(
            quote="a verbatim passage from the source document",
            source_url="https://doi.org/10.1/x", verified_verbatim=True,
        )],
    )


def _orchestrator(tmp_path, reference_checks=None) -> ClaimOrchestrator:
    run_paths = RunPaths.for_pdf("paper.pdf", runs_root=tmp_path)
    orc = object.__new__(ClaimOrchestrator)
    orc.run_paths = run_paths
    orc.output_dir = run_paths.validation_results
    orc._log_path = run_paths.orchestration_log()
    orc.llm_client = FakeCostClient()
    orc.reference_checks = reference_checks or {}
    return orc


def _summary(orc):
    with open(orc.run_paths.run_summary_json(), encoding="utf-8") as f:
        return json.load(f)


def test_all_abstention_run_does_not_crash_the_summary():
    """The regression guard: every confidence is None after Tier 0.1."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        orc = _orchestrator(tmp)
        claims = [_claim("c1"), _claim("c2")]
        results = {
            "qualitative_uncited": [
                not_checkable(c, NotCheckableReason.NO_SOURCE_AVAILABLE, "no source")
                for c in claims
            ],
            "quantitative_uncited": [], "qualitative_cited": [], "quantitative_cited": [],
        }
        orc._save_run_summary(claims, results, {}, 0.0)

        summary = _summary(orc)
        step = summary["steps"]["qualitative_uncited"]
        assert step["count"] == 2
        assert step["checkable"] == 0
        assert step["avg_confidence"] is None
        assert step["verdicts"]["not_checkable"] == 2
        assert step["not_checkable_reasons"]["no_source_available"] == 2


def test_substantiation_rate_is_over_checkable_claims(tmp_path):
    orc = _orchestrator(tmp_path)
    claims = [_claim(f"c{i}") for i in range(4)]
    results = {
        "qualitative_uncited": [
            not_checkable(claims[0], NotCheckableReason.NO_SOURCE_AVAILABLE, "x"),
            not_checkable(claims[1], NotCheckableReason.ABSTRACT_ONLY, "x"),
        ],
        "quantitative_uncited": [],
        "qualitative_cited": [
            ValidationBatch(
                citation_id="7", download_successful=True, judgeable=True,
                claim_results=[
                    _judgment("c2", Verdict.SUBSTANTIATED),
                    _judgment("c3", Verdict.NOT_SUBSTANTIATED, 0.4),
                ],
                batch_notes="ok",
            )
        ],
        "quantitative_cited": [],
    }
    orc._save_run_summary(claims, results, {}, 0.0)

    totals = _summary(orc)["totals"]
    assert totals["claims"] == 4
    assert totals["checkable"] == 2
    assert totals["checkable_rate"] == 0.5
    # 1 substantiated out of 2 *checkable*, not out of 4.
    assert totals["substantiation_rate"] == 0.5
    assert totals["evidence_backed_verdicts"] == 2


def test_summary_records_every_abstention_reason(tmp_path):
    orc = _orchestrator(tmp_path)
    claims = [_claim(f"c{i}") for i in range(3)]
    results = {
        "qualitative_uncited": [
            not_checkable(claims[0], NotCheckableReason.NO_SOURCE_AVAILABLE, "x"),
            not_checkable(claims[1], NotCheckableReason.ABSTRACT_ONLY, "x"),
            not_checkable(claims[2], NotCheckableReason.REFERENCE_NOT_FOUND, "x"),
        ],
        "quantitative_uncited": [], "qualitative_cited": [], "quantitative_cited": [],
    }
    orc._save_run_summary(claims, results, {}, 0.0)

    reasons = _summary(orc)["not_checkable_reasons"]
    assert reasons == {
        "abstract_only": 1, "no_source_available": 1, "reference_not_found": 1,
    }


def test_reference_audit_rollup_is_written(tmp_path):
    checks = {
        "1": ReferenceCheck(citation_id="1", raw_citation_text="a",
                            status=ReferenceStatus.VERIFIED),
        "2": ReferenceCheck(citation_id="2", raw_citation_text="b",
                            status=ReferenceStatus.NOT_FOUND_IN_INDEXES),
        "3": ReferenceCheck(citation_id="3", raw_citation_text="c",
                            status=ReferenceStatus.VERIFIED,
                            retraction_status=RetractionStatus.RETRACTED),
    }
    orc = _orchestrator(tmp_path, checks)
    orc._save_run_summary([], {"qualitative_uncited": [], "quantitative_uncited": [],
                               "qualitative_cited": [], "quantitative_cited": []}, {}, 0.0)

    audit = _summary(orc)["reference_audit"]
    assert audit["total"] == 3
    assert audit["verified"] == 2
    assert audit["not_found_in_indexes"] == 1
    assert audit["retracted"] == 1


def test_results_files_are_stamped_with_the_schema_version(tmp_path):
    orc = _orchestrator(tmp_path)
    claim = _claim("c1")
    orc._save_results({
        "qualitative_uncited": [
            not_checkable(claim, NotCheckableReason.NO_SOURCE_AVAILABLE, "x")
        ],
        "quantitative_uncited": [], "qualitative_cited": [], "quantitative_cited": [],
    })

    with open(orc.run_paths.results_schema_json(), encoding="utf-8") as f:
        assert json.load(f)["schema_version"] == 2

    path = orc.output_dir / "qualitative_uncited_results.json"
    with open(path, encoding="utf-8") as f:
        entries = json.load(f)
    # The list shape is preserved: every analysis snippet in the project's own
    # docs depends on it, including the ones that produced the published numbers.
    assert isinstance(entries, list)
    assert entries[0]["verdict"] == "not_checkable"
    assert entries[0]["confidence"] is None
    assert entries[0]["passed"] is False
