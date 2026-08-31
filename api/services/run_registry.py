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

from run_paths import RunPaths, RUNS_ROOT_DIR

from api.schemas import CostSummary, FunnelStage, RunDetail, RunStatus, RunSummaryRow, StepStats, VerdictBreakdown
from api.services.read_model import load_json, load_manifest_by_citation, build_claim_rows


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


def _count_unresolved_and_totals(run_paths: RunPaths) -> Tuple[int, int, int]:
    """Cheap pass over the raw result files (no ClaimObject/claims.json load)
    for the listing view: (passed, failed, unresolved_source) totals."""
    passed = failed = unresolved = 0

    for fname in ("qualitative_uncited_results.json", "quantitative_uncited_results.json"):
        for r in load_json(run_paths.validation_results / fname, []):
            if r.get("validation_method") == "source_not_found":
                unresolved += 1
            elif r.get("passed"):
                passed += 1
            else:
                failed += 1

    for fname in ("qualitative_cited_results.json", "quantitative_cited_results.json"):
        for batch in load_json(run_paths.validation_results / fname, []):
            for cr in batch.get("claim_results", []):
                if not batch.get("download_successful"):
                    unresolved += 1
                elif cr.get("passed"):
                    passed += 1
                else:
                    failed += 1

    return passed, failed, unresolved


def list_runs() -> List[RunSummaryRow]:
    rows: List[RunSummaryRow] = []
    for run_dir in list_run_dirs():
        try:
            run_paths = RunPaths.from_existing(run_dir)
        except ValueError:
            continue
        status, domains = resolve_status(run_paths)
        summary = load_json(run_paths.run_summary_json(), None)
        passed, failed, unresolved = _count_unresolved_and_totals(run_paths)
        total_claims = summary["input"]["total_claims"] if summary else (passed + failed + unresolved) or None
        judged = passed + failed
        cost = CostSummary(**summary["cost"]) if summary and summary.get("cost") else None

        rows.append(RunSummaryRow(
            run_id=run_dir.name,
            pdf_stem=run_paths.pdf_stem,
            timestamp=run_paths.timestamp,
            status=status,
            total_claims=total_claims,
            passed=passed,
            failed=failed,
            unresolved_source=unresolved,
            pass_rate=round(passed / judged, 3) if judged else None,
            unresolved_source_rate=round(unresolved / total_claims, 3) if total_claims else None,
            total_elapsed_seconds=summary.get("total_elapsed_seconds") if summary else None,
            cost=cost,
            awaiting_login_domains=domains,
        ))
    return rows


def _verdict_breakdown(run_paths: RunPaths) -> List[VerdictBreakdown]:
    rows = build_claim_rows(run_paths)
    by_group: Dict[str, VerdictBreakdown] = {}
    for row in rows:
        vb = by_group.setdefault(row.group, VerdictBreakdown(group=row.group))
        verdict = row.result.verdict if row.result else "skipped"
        setattr(vb, verdict, getattr(vb, verdict) + 1)
    return list(by_group.values())


def _resolution_funnel(run_paths: RunPaths) -> List[FunnelStage]:
    dataset_entries = list(load_manifest_by_citation(run_paths.datasets_manifest_json()).values())
    text_entries = list(load_manifest_by_citation(run_paths.text_sources_manifest_json()).values())
    all_entries = dataset_entries + text_entries

    total = len(all_entries)
    url_found = sum(1 for e in all_entries if e.get("resolution_attempts"))
    downloaded = sum(1 for e in all_entries if e.get("batch_download_successful"))

    return [
        FunnelStage(stage="citations_total", count=total),
        FunnelStage(stage="url_found", count=url_found),
        FunnelStage(stage="downloaded", count=downloaded),
        FunnelStage(stage="text_extracted", count=downloaded),
        FunnelStage(stage="validated", count=downloaded),
    ]


def get_run_detail(run_paths: RunPaths) -> RunDetail:
    status, domains = resolve_status(run_paths)
    summary = load_json(run_paths.run_summary_json(), {}) or {}
    steps = {
        name: StepStats(**stats) for name, stats in summary.get("steps", {}).items()
    }
    cost = CostSummary(**summary["cost"]) if summary.get("cost") else None

    return RunDetail(
        run_id=run_paths.root.name,
        pdf_stem=run_paths.pdf_stem,
        timestamp=run_paths.timestamp,
        status=status,
        total_elapsed_seconds=summary.get("total_elapsed_seconds"),
        cost=cost,
        steps=steps,
        verdict_breakdown=_verdict_breakdown(run_paths),
        resolution_funnel=_resolution_funnel(run_paths),
        awaiting_login_domains=domains,
    )


def delete_run(run_dir: Path) -> None:
    import shutil
    shutil.rmtree(run_dir)
