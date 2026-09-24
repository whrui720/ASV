"""Golden-file tests for the 4-file -> ClaimRow[] normalizer (§13).

Verifies against the run's own run_summary.json (produced independently by
the orchestrator) rather than hand-picked expected numbers, so the test
stays correct if the fixture run folder is ever regenerated.
"""

import json
from collections import Counter

import pytest

from asv.core.verdicts import EVIDENCED_VERDICTS, NotCheckableReason, Verdict

from apps.api.services import read_model


def _load_summary(run_paths):
    with open(run_paths.run_summary_json(), encoding="utf-8") as f:
        return json.load(f)


def test_claim_row_count_matches_claims_json(sample_run_paths):
    rows = read_model.build_claim_rows(sample_run_paths, use_cache=False)
    with open(sample_run_paths.claims_json(), encoding="utf-8") as f:
        claims_data = json.load(f)
    assert len(rows) == len(claims_data["claims"])


def test_claim_counts_reconcile_with_run_summary(sample_run_paths):
    """Every claim in a step is accounted for by exactly one verdict.

    The fixture run predates Tier 0, so its own run_summary.json still reports
    the old passed/failed split. Only `count` is comparable across the schema
    change — the verdicts themselves are remapped on read (see
    `test_legacy_plausibility_rows_are_abstentions`)."""
    rows = read_model.build_claim_rows(sample_run_paths, use_cache=False)
    summary = _load_summary(sample_run_paths)

    step_to_group = {
        "qualitative_uncited": "qual_uncited",
        "quantitative_uncited": "quant_uncited",
        "qualitative_cited": "qual_cited",
        "quantitative_cited": "quant_cited",
    }

    for step_name, group in step_to_group.items():
        step_stats = summary["steps"][step_name]
        group_rows = [r for r in rows if r.group == group]
        counts = Counter(
            r.result.verdict.value if r.result else "missing" for r in group_rows
        )
        assert sum(counts.values()) == step_stats["count"], f"{group}: count mismatch"
        assert set(counts) <= {v.value for v in Verdict} | {"missing"}


def test_legacy_plausibility_rows_are_abstentions(sample_run_paths):
    """Tier 0.1/0.2: a pre-Tier-0 "pass" from the plausibility path must not
    render as `substantiated`.

    On this fixture run, 217 of 224 passes came from asking a model whether a
    sentence sounded plausible, with `sources_used: []`. Showing those as
    substantiated in the new UI would reproduce exactly the claim Tier 0 exists
    to stop making. The raw run files are untouched; only the rendering changes,
    and the original boolean is preserved in validation_metadata."""
    rows = read_model.build_claim_rows(sample_run_paths, use_cache=False)
    plausibility = [
        r for r in rows
        if r.result and r.result.method in read_model._LEGACY_PLAUSIBILITY_METHODS
    ]
    assert plausibility, "fixture run should contain plausibility-path results"
    for r in plausibility:
        assert r.result.verdict == Verdict.NOT_CHECKABLE
        assert r.result.not_checkable_reason == NotCheckableReason.NO_SOURCE_AVAILABLE
        assert r.result.legacy is True
        assert "legacy_passed" in (r.result.validation_metadata or {})


def test_no_abstention_carries_a_confidence(sample_run_paths):
    """A number attached to "I could not check this" is the exact shape of
    unearned confidence Tier 0 removes — including on legacy runs."""
    rows = read_model.build_claim_rows(sample_run_paths, use_cache=False)
    offenders = [
        r.claim_id for r in rows
        if r.result
        and r.result.verdict == Verdict.NOT_CHECKABLE
        and r.result.confidence is not None
    ]
    assert not offenders, f"abstentions carrying a confidence: {offenders[:5]}"


def test_no_judgment_without_evidence(sample_run_paths):
    """Tier 0.5 holds at the read boundary too: any row rendered as a judgment
    must carry a verbatim-verified span and a source URL. Legacy rows predate
    evidence capture, so they are exempt and flagged as such."""
    rows = read_model.build_claim_rows(sample_run_paths, use_cache=False)
    for r in rows:
        if r.result is None or r.result.legacy:
            continue
        if r.result.verdict in EVIDENCED_VERDICTS:
            assert r.result.evidence, f"{r.claim_id}: judgment with no evidence"
            assert any(e.verified_verbatim for e in r.result.evidence)
            assert r.result.source_url


def test_cited_claims_have_batch_context(sample_run_paths):
    rows = read_model.build_claim_rows(sample_run_paths, use_cache=False)
    cited_rows = [r for r in rows if r.group in ("qual_cited", "quant_cited") and r.result]
    assert cited_rows, "expected at least one cited claim in the fixture run"
    for r in cited_rows:
        assert r.batch is not None
        assert r.batch.citation_id
        # A failed download must surface as an abstention with a source-side
        # reason, never as a judgment about the claim.
        if not r.batch.download_successful:
            assert r.result.verdict == Verdict.NOT_CHECKABLE
            assert r.result.not_checkable_reason in (
                NotCheckableReason.SOURCE_DOWNLOAD_FAILED,
                NotCheckableReason.SOURCE_NOT_RESOLVED,
            )


def test_uncited_claims_have_no_batch(sample_run_paths):
    rows = read_model.build_claim_rows(sample_run_paths, use_cache=False)
    uncited_rows = [r for r in rows if r.group in ("qual_uncited", "quant_uncited")]
    assert uncited_rows
    assert all(r.batch is None for r in uncited_rows)


def test_cache_returns_stable_rows_until_files_change(sample_run_paths):
    first = read_model.build_claim_rows(sample_run_paths, use_cache=True)
    second = read_model.build_claim_rows(sample_run_paths, use_cache=True)
    assert first == second


def test_get_claim_row_and_siblings(sample_run_paths):
    rows = read_model.build_claim_rows(sample_run_paths, use_cache=False)
    cited_with_siblings = next(
        (r for r in rows if r.batch and len(r.batch.sibling_claim_ids) > 1), None
    )
    if cited_with_siblings is None:
        pytest.skip("fixture run has no multi-claim citation batch")

    row = read_model.get_claim_row(sample_run_paths, cited_with_siblings.claim_id)
    assert row is not None
    assert row.claim_id == cited_with_siblings.claim_id

    siblings = read_model.get_sibling_rows(sample_run_paths, row)
    sibling_ids = {s.claim_id for s in siblings}
    assert row.claim_id not in sibling_ids
    assert sibling_ids == set(row.batch.sibling_claim_ids) - {row.claim_id}
