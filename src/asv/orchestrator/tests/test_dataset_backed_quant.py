"""The dataset-backed quantitative path under the Tier 0 contract.

This path is marked for removal in VALUE_PROPOSITION.md Tier 4 — LLM-written
pandas scripts hallucinate columns, run against non-datasets, and execute
unsandboxed. Tier 0 does not cut it, but it does hold it to the same rule as
every other path: no verdict without something a human can check. Here that is
the executed script's own output, which is deterministic and reproducible by
re-running the script stored beside it.
"""

import pytest

from asv.core.models import CitationDetails, ClaimObject, FoundDatasetSource
from asv.core.run_paths import RunPaths
from asv.core.verdicts import NotCheckableReason, Verdict
from asv.orchestrator import claim_orchestrator as co

pytestmark = pytest.mark.unit


class StubLLM:
    def call_llm(self, prompt, **kwargs):
        return {}

    def get_cost_summary(self):
        return {"input_tokens": 0, "output_tokens": 0, "total_cost": 0.0}


class StubScriptValidator:
    """Stands in for PythonScriptValidator, which shells out to `python`."""

    def __init__(self, result):
        self.result = result

    def validate(self, claim_text, dataset_path, claim_id):
        return self.result


class StubDatasetDownloader:
    def __init__(self, ok=True):
        self.ok = ok

    def download(self, url, citation_id):
        if not self.ok:
            return {'downloaded': False, 'error': '404 Not Found'}
        return {
            'downloaded': True, 'path': f"/tmp/citation_{citation_id}_dataset.csv",
            'format': 'csv', 'error': None,
        }

    def delete_dataset(self, filename):
        return {'deleted': True, 'error': None}


def _claim() -> ClaimObject:
    return ClaimObject(
        claim_id="q1", text="Mean household income rose 4.2% in 2021.",
        claim_type="quantitative", citation_found=True,
        citation_id="found_q1", citation_text="[Found: data.gov]",
        citation_details=CitationDetails(url="https://data.gov/x.csv", raw_text="dataset"),
        originally_uncited=True,
        found_source=FoundDatasetSource(
            source_url="https://data.gov/x.csv", source_type="data.gov",
            relevance_score=0.7, found_by_claim_id="q1",
        ),
    )


def _orchestrator(tmp_path, monkeypatch, script_result, download_ok=True):
    monkeypatch.setattr(co, "LLMClient", StubLLM)
    monkeypatch.setattr(co, "ReferenceVerifier", lambda **k: None)
    run_paths = RunPaths.for_pdf("paper.pdf", runs_root=tmp_path)
    orc = co.ClaimOrchestrator(run_paths=run_paths)
    orc.reference_checks = {}
    orc.dataset_downloader = StubDatasetDownloader(download_ok)
    orc.quant_processor.script_tool = StubScriptValidator(script_result)
    return orc


SUCCESS = {
    'validated': True, 'passed': True, 'confidence': 0.9,
    'explanation': "Recomputed mean matches the claimed 4.2% increase.",
    'raw_output': '{"passed": true, "confidence": 0.9, "computed_change_pct": 4.21}',
    'error': None,
}


def test_successful_script_run_carries_its_output_as_evidence(tmp_path, monkeypatch):
    orc = _orchestrator(tmp_path, monkeypatch, SUCCESS)
    (batch,) = orc._process_dataset_backed_quant([_claim()])

    assert batch.download_successful is True
    assert batch.judgeable is True
    (result,) = batch.claim_results
    assert result.verdict == Verdict.SUBSTANTIATED
    assert result.evidence
    span = result.evidence[0]
    assert span.verified_verbatim
    assert "computed_change_pct" in span.quote
    assert span.locator == "generated_scripts/validate_q1.py"
    assert result.source_url == "https://data.gov/x.csv"


def test_script_that_did_not_run_abstains(tmp_path, monkeypatch):
    orc = _orchestrator(tmp_path, monkeypatch, {
        'validated': False, 'passed': False, 'confidence': 0.0,
        'explanation': "Failed to generate validation script",
        'error': "Script generation failed",
    })
    (batch,) = orc._process_dataset_backed_quant([_claim()])
    (result,) = batch.claim_results
    assert result.verdict == Verdict.NOT_CHECKABLE
    assert result.not_checkable_reason == NotCheckableReason.VALIDATION_ERROR
    assert result.confidence is None


def test_script_with_no_inspectable_output_abstains(tmp_path, monkeypatch):
    """A verdict backed only by the script's say-so is not checkable by a human,
    so it is not a verdict."""
    orc = _orchestrator(tmp_path, monkeypatch, {
        **SUCCESS, 'raw_output': '',
    })
    (batch,) = orc._process_dataset_backed_quant([_claim()])
    (result,) = batch.claim_results
    assert result.verdict == Verdict.NOT_CHECKABLE
    assert result.not_checkable_reason == NotCheckableReason.EVIDENCE_UNVERIFIABLE


def test_failed_download_abstains_rather_than_failing_the_claim(tmp_path, monkeypatch):
    orc = _orchestrator(tmp_path, monkeypatch, SUCCESS, download_ok=False)
    (batch,) = orc._process_dataset_backed_quant([_claim()])

    assert batch.download_successful is False
    assert batch.judgeable is False
    (result,) = batch.claim_results
    assert result.verdict == Verdict.NOT_CHECKABLE
    assert result.not_checkable_reason == NotCheckableReason.SOURCE_DOWNLOAD_FAILED
    assert result.confidence is None
