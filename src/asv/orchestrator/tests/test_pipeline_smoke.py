"""End-to-end orchestration with every external call stubbed.

Covers the wiring Tier 0 changed most: the bibliography audit running as step 0
and feeding DOIs forward, the three-way batch outcome, the evidence invariant
holding across a real ``process_claims`` call, and the run summary surviving a
run that is mostly abstentions.

This is the test that would have caught any of the five rewrites in
TIER0_PLAN.md §8 breaking the others.
"""

import json

import pytest

from asv.core.models import CitationDetails, ClaimObject, ReferenceCheck
from asv.core.run_paths import RunPaths
from asv.core.verdicts import (
    ContentQuality, NotCheckableReason, ReferenceStatus, RetractionStatus, Verdict,
)
from asv.orchestrator import claim_orchestrator as co

pytestmark = pytest.mark.integration


FULL_TEXT = (
    "Introduction\n" + ("Framing prose about the virus. " * 120)
    + "\n\nMaterials and Methods\n" + ("Cells were cultured and infected. " * 120)
    + "\n\nResults\n"
    + "Viral titres peaked at 24 hours post-infection, reaching 6.2 log10 PFU/ml.\n"
    + ("Further results prose. " * 120)
    + "\n\nDiscussion\n" + ("Interpretation and limitations. " * 120)
)

LANDING_PAGE = (
    "A review of oncolytic virotherapy\n\nAbstract\n"
    + ("A summary of the field. " * 30)
    + "\n\nReferences\n"
    + "".join(f"{i}. Author A. A title. J Virol 2011; 9{i % 10}: 1{i}20.\n" for i in range(1, 45))
)


class StubLLM:
    """Returns a well-formed, verifiable verdict for every judgment call."""

    def __init__(self):
        self.calls = []

    def call_llm(self, prompt, **kwargs):
        self.calls.append(kwargs.get("task_name"))
        return {
            "verdict": "substantiated",
            "confidence": 0.82,
            "explanation": "The Results section states the peak titre directly.",
            "quotes": [{
                "text": "Viral titres peaked at 24 hours post-infection",
                "role": "supporting",
            }],
        }

    def get_cost_summary(self):
        return {"input_tokens": 0, "output_tokens": 0, "total_cost": 0.0}


class StubTextDownloader:
    """Serves full text for citation 1, a landing page for citation 2, and a
    404 for citation 3 — the three outcomes Tier 0.3 distinguishes."""

    def __init__(self, real):
        self._real = real
        self.session = real.session
        self._paper_finder = real._paper_finder
        self.output_dir = real.output_dir

    def download_with_resolution(self, citation_details, citation_id, raw_citation_text):
        cid = str(citation_id)
        if cid == "1":
            return {
                'downloaded': True, 'judgeable': True,
                'content_quality': ContentQuality.FULL_TEXT,
                'content_signals': {'usable_chars': len(FULL_TEXT), 'imrad_count': 4},
                'format': 'html', 'path': str(self.output_dir / "citation_1_text.html"),
                'text_content': FULL_TEXT, 'error': None,
                'attempts': [{'url': 'https://europepmc.org/a', 'source': 'open_access',
                              'downloaded': True, 'content_quality': ContentQuality.FULL_TEXT,
                              'error': None}],
                'winning_url': 'https://europepmc.org/a',
            }
        if cid == "2":
            return {
                'downloaded': True, 'judgeable': False,
                'content_quality': ContentQuality.ABSTRACT_ONLY,
                'content_signals': {'usable_chars': len(LANDING_PAGE), 'imrad_count': 0},
                'format': 'html', 'path': str(self.output_dir / "citation_2_text.html"),
                'text_content': LANDING_PAGE, 'error': None,
                'attempts': [{'url': 'https://www.nature.com/b', 'source': 'open_access',
                              'downloaded': True, 'content_quality': ContentQuality.ABSTRACT_ONLY,
                              'error': None}],
                'winning_url': 'https://www.nature.com/b',
            }
        return {
            'downloaded': False, 'judgeable': False, 'content_quality': None,
            'content_signals': None, 'format': None, 'path': None,
            'text_content': None, 'error': '403 Forbidden',
            'attempts': [{'url': 'https://wiley.com/c', 'source': 'open_access',
                          'downloaded': False, 'content_quality': None, 'error': '403'}],
            'winning_url': None,
        }

    def delete_text(self, filename):
        return {'deleted': True, 'path': filename, 'error': None}


class StubReferenceVerifier:
    def __init__(self, *a, **k):
        pass

    def verify_all(self, citations, on_progress=None):
        out = {}
        for cid in citations:
            out[str(cid)] = ReferenceCheck(
                citation_id=str(cid),
                raw_citation_text=citations[cid],
                status=ReferenceStatus.VERIFIED,
                matched_doi=f"10.1234/ref{cid}",
                matched_url=f"https://doi.org/10.1234/ref{cid}",
                # Citation 3's source is retracted — a flag, never a verdict.
                retraction_status=(
                    RetractionStatus.RETRACTED if str(cid) == "3" else RetractionStatus.NONE
                ),
                explanation="matched",
            )
        return out

    def flush_cache(self):
        pass


def _claim(cid, citation_id=None, quantitative=False, original=False) -> ClaimObject:
    return ClaimObject(
        claim_id=cid,
        text="Viral titres peaked at 24 hours post-infection, reaching 6.2 log10 PFU/ml.",
        claim_type="quantitative" if quantitative else "qualitative",
        citation_found=citation_id is not None,
        citation_id=citation_id,
        citation_text=f"[{citation_id}]" if citation_id else None,
        citation_details=(
            CitationDetails(raw_text=f"ref {citation_id}") if citation_id else None
        ),
        is_original=original,
    )


@pytest.fixture
def orchestrator(tmp_path, monkeypatch):
    monkeypatch.setattr(co, "LLMClient", StubLLM)
    monkeypatch.setattr(co, "ReferenceVerifier", StubReferenceVerifier)
    monkeypatch.setattr(co.ClaimOrchestrator, "_setup_browser_searcher",
                        lambda self, claims, citations: None)

    run_paths = RunPaths.for_pdf("paper.pdf", runs_root=tmp_path)
    orc = co.ClaimOrchestrator(run_paths=run_paths)
    orc.text_downloader = StubTextDownloader(orc.text_downloader)
    orc.qual_processor.llm_tool.llm_client = orc.llm_client
    return orc


CLAIMS = [
    _claim("c1"),                       # uncited
    _claim("c2", original=True),        # uncited, claimed original
    _claim("c3", citation_id="1"),      # full text -> judged
    _claim("c4", citation_id="1"),      # same batch
    _claim("c5", citation_id="2"),      # abstract only -> abstain
    _claim("c6", citation_id="3"),      # download failed -> abstain
]
CITATIONS = {"1": "Ref one 1991", "2": "Ref two 2005", "3": "Ref three 2012"}


def test_pipeline_runs_and_writes_every_artifact(orchestrator):
    results = orchestrator.process_claims(list(CLAIMS), dict(CITATIONS))

    rp = orchestrator.run_paths
    assert rp.run_summary_json().exists()
    assert rp.reference_checks_json().exists()
    assert rp.results_schema_json().exists()
    for name in ("qualitative_uncited", "qualitative_cited"):
        assert (rp.validation_results / f"{name}_results.json").exists()

    flat = [
        cr for group in results.values() for item in group
        for cr in (item.claim_results if hasattr(item, "claim_results") else [item])
    ]
    assert len(flat) == len(CLAIMS)


def test_every_verdict_is_earned(orchestrator):
    """The Tier 0.5 invariant, end to end: no judgment without a verified quote
    and a resolvable URL."""
    results = orchestrator.process_claims(list(CLAIMS), dict(CITATIONS))
    by_id = {
        cr.claim_id: cr
        for group in results.values() for item in group
        for cr in (item.claim_results if hasattr(item, "claim_results") else [item])
    }

    for claim_id in ("c3", "c4"):
        r = by_id[claim_id]
        assert r.verdict == Verdict.SUBSTANTIATED
        assert r.evidence and any(e.verified_verbatim for e in r.evidence)
        assert r.source_url == "https://europepmc.org/a"
        assert r.confidence == 0.82
        assert r.content_quality == ContentQuality.FULL_TEXT


def test_uncited_and_unusable_sources_all_abstain(orchestrator):
    results = orchestrator.process_claims(list(CLAIMS), dict(CITATIONS))
    by_id = {
        cr.claim_id: cr
        for group in results.values() for item in group
        for cr in (item.claim_results if hasattr(item, "claim_results") else [item])
    }

    assert by_id["c1"].not_checkable_reason == NotCheckableReason.NO_SOURCE_AVAILABLE
    assert by_id["c2"].not_checkable_reason == NotCheckableReason.ORIGINAL_CONTRIBUTION
    # Fetched successfully, and still refused — this is the whole of Tier 0.3.
    assert by_id["c5"].not_checkable_reason == NotCheckableReason.ABSTRACT_ONLY
    assert by_id["c6"].not_checkable_reason == NotCheckableReason.SOURCE_DOWNLOAD_FAILED
    for cid in ("c1", "c2", "c5", "c6"):
        assert by_id[cid].confidence is None


def test_no_llm_call_is_made_for_unjudgeable_batches(orchestrator):
    """Cost: the abstract-only batch and the failed batch must not reach the
    verification model at all."""
    orchestrator.process_claims(list(CLAIMS), dict(CITATIONS))
    verification_calls = [
        t for t in orchestrator.llm_client.calls if t == "source_grounded_verification"
    ]
    assert len(verification_calls) == 2  # c3 and c4 only


def test_retracted_source_flags_the_claim_without_changing_its_verdict(orchestrator):
    results = orchestrator.process_claims(list(CLAIMS), dict(CITATIONS))
    by_id = {
        cr.claim_id: cr
        for group in results.values() for item in group
        for cr in (item.claim_results if hasattr(item, "claim_results") else [item])
    }
    assert "cited_source_retracted" in by_id["c6"].flags
    assert by_id["c6"].verdict == Verdict.NOT_CHECKABLE


def test_verified_dois_are_fed_into_resolution(orchestrator):
    """The acquisition side-benefit: a reference the audit verified arrives at
    the resolver with a DOI already attached, rather than being rediscovered
    at the end of the cascade."""
    claims = list(CLAIMS)
    orchestrator.process_claims(claims, dict(CITATIONS))
    cited = [c for c in claims if c.citation_id]
    assert cited
    for claim in cited:
        assert claim.citation_details.doi == f"10.1234/ref{claim.citation_id}"


def test_run_summary_reports_checkable_rate_not_pass_rate(orchestrator):
    orchestrator.process_claims(list(CLAIMS), dict(CITATIONS))
    with open(orchestrator.run_paths.run_summary_json(), encoding="utf-8") as f:
        summary = json.load(f)

    totals = summary["totals"]
    assert totals["claims"] == 6
    assert totals["checkable"] == 2
    assert totals["checkable_rate"] == round(2 / 6, 3)
    assert totals["substantiation_rate"] == 1.0
    assert totals["evidence_backed_verdicts"] == 2
    assert summary["reference_audit"]["total"] == 3
    assert summary["reference_audit"]["retracted"] == 1
    assert summary["not_checkable_reasons"]["abstract_only"] == 1


def test_results_are_readable_by_the_api(orchestrator):
    """The read model must round-trip what the orchestrator writes — the two
    have separate notions of the schema and this is where they meet."""
    from apps.api.services import read_model

    claims = list(CLAIMS)
    orchestrator.process_claims(claims, dict(CITATIONS))

    # The extractor normally writes this; the read model joins results back
    # onto it, so the smoke test has to stand in for that step.
    with open(orchestrator.run_paths.claims_json(), "w", encoding="utf-8") as f:
        json.dump(
            {"claims": [c.model_dump(mode="json") for c in claims], "citations": CITATIONS},
            f,
        )

    rows = read_model.build_claim_rows(orchestrator.run_paths, use_cache=False)

    assert len(rows) == len(CLAIMS)
    assert all(not r.result.legacy for r in rows), "fresh run must not read as legacy"
    assert read_model.schema_version(orchestrator.run_paths) == 2
    judged = [r for r in rows if r.result.verdict != Verdict.NOT_CHECKABLE]
    assert len(judged) == 2
    assert all(r.result.evidence for r in judged)
