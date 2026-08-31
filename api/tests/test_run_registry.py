"""Run listing/status resolution against every committed fixture run folder."""

from run_paths import RunPaths

from api.services import run_registry


def test_list_runs_covers_all_fixture_folders(all_run_dirs):
    rows = run_registry.list_runs()
    listed_ids = {r.run_id for r in rows}
    for d in all_run_dirs:
        assert d.name in listed_ids


def test_every_run_resolves_a_valid_status(all_run_dirs):
    valid_statuses = {"queued", "running", "awaiting_login", "complete", "failed"}
    for d in all_run_dirs:
        run_paths = RunPaths.from_existing(d)
        status, domains = run_registry.resolve_status(run_paths)
        assert status in valid_statuses
        assert isinstance(domains, list)


def test_completed_run_infers_complete_without_status_json(sample_run_paths):
    # None of the fixture runs were launched through the API, so none have a
    # status.json — status must come entirely from run_summary.json presence.
    assert not sample_run_paths.status_json().exists()
    status, domains = run_registry.resolve_status(sample_run_paths)
    assert status == "complete"
    assert domains == []


def test_run_detail_has_consistent_verdict_breakdown(sample_run_paths):
    detail = run_registry.get_run_detail(sample_run_paths)
    total_from_breakdown = sum(
        vb.passed + vb.failed + vb.unresolved_source + vb.skipped for vb in detail.verdict_breakdown
    )
    assert total_from_breakdown == detail.steps["qualitative_uncited"].count + \
        detail.steps["quantitative_uncited"].count + \
        detail.steps["qualitative_cited"].count + \
        detail.steps["quantitative_cited"].count
