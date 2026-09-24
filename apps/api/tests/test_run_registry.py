"""Run listing/status resolution against every committed fixture run folder."""

from asv.core.run_paths import RunPaths

from apps.api.services import run_registry


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
        vb.substantiated
        + vb.partially_substantiated
        + vb.not_substantiated
        + vb.contradicted
        + vb.not_checkable
        for vb in detail.verdict_breakdown
    )
    assert total_from_breakdown == sum(
        detail.steps[s].count for s in (
            "qualitative_uncited", "quantitative_uncited",
            "qualitative_cited", "quantitative_cited",
        )
    )


def test_not_checkable_reasons_account_for_every_abstention(sample_run_paths):
    """Tier 0.2: an abstention without a reason code is useless to a reader —
    "paywalled" and "the reference does not exist" imply opposite actions."""
    detail = run_registry.get_run_detail(sample_run_paths)
    abstentions = sum(vb.not_checkable for vb in detail.verdict_breakdown)
    assert sum(detail.not_checkable_reasons.values()) == abstentions


def test_substantiation_rate_is_over_checkable_claims(sample_run_paths):
    """The old pass_rate divided by passed+failed, which put 217 unsourced
    plausibility passes in its numerator and reported 73%. The replacement is
    computed over claims that could actually be checked."""
    row = next(
        r for r in run_registry.list_runs() if r.run_id == sample_run_paths.root.name
    )
    checkable = (
        row.substantiated + row.partially_substantiated
        + row.not_substantiated + row.contradicted
    )
    assert row.total_claims == checkable + row.not_checkable
    if checkable:
        assert row.substantiation_rate == round(row.substantiated / checkable, 3)
    assert row.checkable_rate == round(checkable / row.total_claims, 3)
