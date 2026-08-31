"""Golden-file tests for the 4-file -> ClaimRow[] normalizer (§13).

Verifies against the run's own run_summary.json (produced independently by
the orchestrator) rather than hand-picked expected numbers, so the test
stays correct if the fixture run folder is ever regenerated.
"""

import json

import pytest

from api.services import read_model


def _load_summary(run_paths):
    with open(run_paths.run_summary_json(), encoding="utf-8") as f:
        return json.load(f)


def test_claim_row_count_matches_claims_json(sample_run_paths):
    rows = read_model.build_claim_rows(sample_run_paths, use_cache=False)
    with open(sample_run_paths.claims_json(), encoding="utf-8") as f:
        claims_data = json.load(f)
    assert len(rows) == len(claims_data["claims"])


def test_verdict_counts_reconcile_with_run_summary(sample_run_paths):
    """run_summary.json's `failed` count folds together what the read model
    splits into `failed` and `unresolved_source` — the two must sum back to
    it, and `passed`/`count` must match exactly."""
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

        passed = sum(1 for r in group_rows if r.result and r.result.verdict == "passed")
        failed = sum(1 for r in group_rows if r.result and r.result.verdict == "failed")
        unresolved = sum(1 for r in group_rows if r.result and r.result.verdict == "unresolved_source")
        skipped = sum(1 for r in group_rows if r.result is None or r.result.verdict == "skipped")

        assert passed == step_stats["passed"], f"{group}: passed mismatch"
        assert failed + unresolved == step_stats["failed"], f"{group}: failed+unresolved mismatch"
        assert passed + failed + unresolved + skipped == step_stats["count"], f"{group}: count mismatch"


def test_cited_claims_have_batch_context(sample_run_paths):
    rows = read_model.build_claim_rows(sample_run_paths, use_cache=False)
    cited_rows = [r for r in rows if r.group in ("qual_cited", "quant_cited") and r.result]
    assert cited_rows, "expected at least one cited claim in the fixture run"
    for r in cited_rows:
        assert r.batch is not None
        assert r.batch.citation_id
        # download_successful=False must always surface as unresolved_source,
        # never as a bare "failed" (the core distinction driving the plan).
        if not r.batch.download_successful:
            assert r.result.verdict == "unresolved_source"


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
