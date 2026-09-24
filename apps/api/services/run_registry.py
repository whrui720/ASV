"""Run discovery + status. No database — ``runs/`` on disk is the index.

Status resolution order:
  1. ``status.json`` if present — written live by ``job_manager`` for any run
     launched through the API (queued/running/awaiting_login/complete/failed).
  2. Inferred from file presence, for runs that predate ``status.json`` or
     were launched from the CLI directly:
       - ``final_output/run_summary.json`` exists → "complete"
       - ``logs/events.jsonl`` ends in an unanswered ``awaiting_login`` → "awaiting_login"
       - ``logs/events.jsonl`` exists but never reached ``run_finished`` and no
         summary → "failed" (a read-only scan can't tell "crashed" from "still
         running" for a CLI process it doesn't own, and treating a genuinely
         still-running CLI run as failed is a rare, self-correcting cost —
         the very next request re-reads the same evidence.
       - Neither exists → "failed" (run folder created, extraction never completed)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from asv.core.run_paths import RunPaths, RUNS_ROOT_DIR
from asv.core.verdicts import ContentQuality, ReferenceStatus, RetractionStatus, Verdict

from apps.api.schemas import (
    CostSummary, FunnelStage, ReferenceAudit, ReferenceCheckRow, RunDetail, RunStatus,
    RunSummaryRow, StepStats, VerdictBreakdown,
)
from apps.api.services.read_model import (
    build_claim_rows, load_json, load_manifest_by_citation, load_reference_checks,
    schema_version,
)


def runs_root() -> Path:
    return Path(RUNS_ROOT_DIR)


def list_run_dirs() -> List[Path]:
    root = runs_root()
    if not root.exists():
        return []
    return sorted(
        (p for p in root.iterdir() if p.is_dir() and "__" in p.name),
        key=lambda p: p.name,
        reverse=True,
    )


def _read_status_json(run_paths: RunPaths) -> Optional[dict]:
    return load_json(run_paths.status_json(), None)


def _tail_events(run_paths: RunPaths, max_lines: int = 200) -> List[dict]:
    path = run_paths.events_jsonl()
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-max_lines:]
    out = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def resolve_status(run_paths: RunPaths) -> Tuple[RunStatus, List[str]]:
    """Return (status, awaiting_login_domains)."""
    explicit = _read_status_json(run_paths)
    if explicit is not None:
        return explicit.get("status", "failed"), explicit.get("awaiting_login_domains", [])

    if run_paths.run_summary_json().exists():
        return "complete", []

    events = _tail_events(run_paths)
    if events:
        # Walk backwards for the most recent login-related event.
        for e in reversed(events):
            if e.get("type") == "login_complete" or e.get("type") == "login_timeout":
                break
            if e.get("type") == "awaiting_login":
                return "awaiting_login", e.get("domains", [])
        for e in events:
            if e.get("type") == "run_finished":
                return "complete", []
        return "failed", []

    return "failed", []


def _verdict_totals(run_paths: RunPaths) -> Tuple[Dict[str, int], int]:
    """Run-level verdict counts, plus how many carry evidence.

    This used to be a hand-rolled pass over the raw result files so the listing
    view could skip loading claims.json. It now goes through ``build_claim_rows``
    instead: that is the one place allowed to know how each schema version is
    shaped, and duplicating the legacy mapping here would let the listing and
    the detail view disagree about the same run. ``build_claim_rows`` is cached
    on file mtime, so the cost is paid once.
    """
    counts = {v.value: 0 for v in Verdict}
    evidenced = 0
    for row in build_claim_rows(run_paths):
        if row.result is None:
            continue
        counts[row.result.verdict.value] += 1
        if row.result.evidence:
            evidenced += 1
    return counts, evidenced


def _reference_audit(run_paths: RunPaths) -> Optional[ReferenceAudit]:
    """Tier 0.6 rollup. None for runs made before the bibliography audit."""
    checks = load_reference_checks(run_paths)
    if not checks:
        return None
    audit = ReferenceAudit(total=len(checks))
    for check in checks.values():
        if hasattr(audit, check.status.value):
            setattr(audit, check.status.value, getattr(audit, check.status.value) + 1)
        if check.retraction_status == RetractionStatus.RETRACTED:
            audit.retracted += 1
        elif check.retraction_status == RetractionStatus.CONCERN_RAISED:
            audit.concern_raised += 1
    return audit


def list_runs() -> List[RunSummaryRow]:
    rows: List[RunSummaryRow] = []
    for run_dir in list_run_dirs():
        try:
            run_paths = RunPaths.from_existing(run_dir)
        except ValueError:
            continue
        status, domains = resolve_status(run_paths)
        summary = load_json(run_paths.run_summary_json(), None)
        counts, evidenced = _verdict_totals(run_paths)
        total_claims = sum(counts.values()) or None
        if summary and summary.get("input", {}).get("total_claims"):
            total_claims = summary["input"]["total_claims"]
        checkable = sum(counts.values()) - counts[Verdict.NOT_CHECKABLE.value]
        cost = CostSummary(**summary["cost"]) if summary and summary.get("cost") else None

        rows.append(RunSummaryRow(
            run_id=run_dir.name,
            pdf_stem=run_paths.pdf_stem,
            timestamp=run_paths.timestamp,
            status=status,
            schema_version=schema_version(run_paths),
            total_claims=total_claims,
            substantiated=counts[Verdict.SUBSTANTIATED.value],
            partially_substantiated=counts[Verdict.PARTIALLY_SUBSTANTIATED.value],
            not_substantiated=counts[Verdict.NOT_SUBSTANTIATED.value],
            contradicted=counts[Verdict.CONTRADICTED.value],
            not_checkable=counts[Verdict.NOT_CHECKABLE.value],
            checkable_rate=round(checkable / total_claims, 3) if total_claims else None,
            substantiation_rate=(
                round(counts[Verdict.SUBSTANTIATED.value] / checkable, 3) if checkable else None
            ),
            evidence_backed_verdicts=evidenced,
            reference_audit=_reference_audit(run_paths),
            total_elapsed_seconds=summary.get("total_elapsed_seconds") if summary else None,
            cost=cost,
            awaiting_login_domains=domains,
        ))
    return rows


def _verdict_breakdown(run_paths: RunPaths) -> Tuple[List[VerdictBreakdown], Dict[str, int]]:
    rows = build_claim_rows(run_paths)
    by_group: Dict[str, VerdictBreakdown] = {}
    reasons: Dict[str, int] = {}
    for row in rows:
        vb = by_group.setdefault(row.group, VerdictBreakdown(group=row.group))
        if row.result is None:
            continue
        field = row.result.verdict.value
        setattr(vb, field, getattr(vb, field) + 1)
        if row.result.not_checkable_reason is not None:
            key = row.result.not_checkable_reason.value
            reasons[key] = reasons.get(key, 0) + 1
    return list(by_group.values()), dict(sorted(reasons.items(), key=lambda kv: -kv[1]))


def _resolution_funnel(run_paths: RunPaths) -> List[FunnelStage]:
    dataset_entries = list(load_manifest_by_citation(run_paths.datasets_manifest_json()).values())
    text_entries = list(load_manifest_by_citation(run_paths.text_sources_manifest_json()).values())
    all_entries = dataset_entries + text_entries

    total = len(all_entries)
    url_found = sum(1 for e in all_entries if e.get("resolution_attempts"))
    downloaded = sum(1 for e in all_entries if e.get("batch_download_successful"))
    # Tier 0.3 made this stage real. Previously "downloaded" was copied into
    # "text_extracted" and "validated", so the funnel could not show that 10 of
    # 16 downloads in the reference run were landing pages nothing could be
    # judged against.
    full_text = sum(
        1 for e in all_entries
        if e.get("batch_judgeable")
        or e.get("content_quality") == ContentQuality.FULL_TEXT.value
    )

    return [
        FunnelStage(stage="citations_total", count=total),
        FunnelStage(stage="url_found", count=url_found),
        FunnelStage(stage="downloaded", count=downloaded),
        FunnelStage(stage="full_text", count=full_text),
        FunnelStage(stage="judged", count=full_text),
    ]


def get_run_detail(run_paths: RunPaths) -> RunDetail:
    status, domains = resolve_status(run_paths)
    summary = load_json(run_paths.run_summary_json(), {}) or {}
    steps = {
        name: StepStats(**stats) for name, stats in summary.get("steps", {}).items()
    }
    cost = CostSummary(**summary["cost"]) if summary.get("cost") else None
    breakdown, reasons = _verdict_breakdown(run_paths)

    return RunDetail(
        run_id=run_paths.root.name,
        pdf_stem=run_paths.pdf_stem,
        timestamp=run_paths.timestamp,
        status=status,
        schema_version=schema_version(run_paths),
        total_elapsed_seconds=summary.get("total_elapsed_seconds"),
        cost=cost,
        steps=steps,
        verdict_breakdown=breakdown,
        not_checkable_reasons=reasons,
        resolution_funnel=_resolution_funnel(run_paths),
        reference_audit=_reference_audit(run_paths),
        awaiting_login_domains=domains,
    )


def list_reference_checks(run_paths: RunPaths) -> List[ReferenceCheckRow]:
    """Tier 0.6 — the bibliography audit, with per-reference claim counts."""
    checks = load_reference_checks(run_paths)
    claim_counts: Dict[str, int] = {}
    for row in build_claim_rows(run_paths):
        cid = row.citation.id if row.citation else None
        if cid:
            claim_counts[str(cid)] = claim_counts.get(str(cid), 0) + 1

    # Most alarming first: things a reader must act on, then the merely unknown.
    order = {
        ReferenceStatus.NOT_FOUND_IN_INDEXES: 0,
        ReferenceStatus.AMBIGUOUS: 1,
        ReferenceStatus.UNVERIFIED: 2,
        ReferenceStatus.UNINDEXED_BY_DESIGN: 3,
        ReferenceStatus.VERIFIED: 4,
    }
    rows = [
        ReferenceCheckRow(**check.model_dump(), num_claims=claim_counts.get(cid, 0))
        for cid, check in checks.items()
    ]
    rows.sort(key=lambda r: (
        0 if r.retraction_status == RetractionStatus.RETRACTED else 1,
        order.get(r.status, 9),
        r.citation_id,
    ))
    return rows


def delete_run(run_dir: Path) -> None:
    import shutil
    shutil.rmtree(run_dir)
