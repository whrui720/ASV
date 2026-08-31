"""Subprocess-based job runner — docs/FRONTEND_PLAN.md §4/§5, Phase 2.

Each run is one OS subprocess (``scripts/run_pipeline_api.py``) with its own
run folder, its own Playwright browser, and its own ``status.json``. This
keeps ``scripts/run_pipeline.py`` — the CLI entry point — completely
unchanged: the web backend never imports the orchestrator directly, it always
shells out, exactly the way a human running the CLI would.

A background thread per job tails ``events.jsonl`` so ``status.json`` reflects
``awaiting_login`` while the pipeline is parked at the paywall checkpoint, and
finalizes to ``complete``/``failed`` once the subprocess exits.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

from asv.core.run_paths import RunPaths

_PROJECT_ROOT = Path(__file__).resolve().parents[3]  # apps/api/services/ -> repo root
_RUN_SCRIPT = _PROJECT_ROOT / "scripts" / "run_pipeline_api.py"
_RETRY_SCRIPT = _PROJECT_ROOT / "scripts" / "revalidate_citation.py"


class JobHandle:
    def __init__(self, run_id: str, run_paths: RunPaths, proc: subprocess.Popen):
        self.run_id = run_id
        self.run_paths = run_paths
        self.proc = proc


_jobs: Dict[str, JobHandle] = {}
_jobs_lock = threading.Lock()


def _write_status(run_paths: RunPaths, status: str, domains: List[str]) -> None:
    payload = {"status": status, "awaiting_login_domains": domains}
    try:
        with open(run_paths.status_json(), "w", encoding="utf-8") as f:
            json.dump(payload, f)
    except Exception:
        pass  # a missed status write self-corrects on the next poll tick


def _tail_new_events(path: Path, offset: int) -> tuple[list[dict], int]:
    if not path.exists():
        return [], offset
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        f.seek(offset)
        lines = f.readlines()
        new_offset = f.tell()
    events = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events, new_offset


def _watch(run_id: str, run_paths: RunPaths, proc: subprocess.Popen) -> None:
    offset = 0
    awaiting_domains: List[str] = []
    status = "running"
    events_path = run_paths.events_jsonl()

    while proc.poll() is None:
        new_events, offset = _tail_new_events(events_path, offset)
        for e in new_events:
            t = e.get("type")
            if t == "awaiting_login":
                status, awaiting_domains = "awaiting_login", e.get("domains", [])
            elif t in ("login_complete", "login_timeout"):
                status, awaiting_domains = "running", []
        _write_status(run_paths, status, awaiting_domains)
        time.sleep(1.0)

    if proc.returncode == 0 and run_paths.run_summary_json().exists():
        _write_status(run_paths, "complete", [])
    else:
        _write_status(run_paths, "failed", [])

    with _jobs_lock:
        _jobs.pop(run_id, None)


def launch_run(pdf_path: str) -> str:
    """Create a fresh run folder and spawn the pipeline subprocess for it.
    Returns the new run_id immediately; the run proceeds in the background."""
    run_paths = RunPaths.for_pdf(pdf_path)
    _write_status(run_paths, "queued", [])

    proc = subprocess.Popen(
        [sys.executable, str(_RUN_SCRIPT), str(pdf_path), str(run_paths.root)],
        cwd=str(_PROJECT_ROOT),
    )
    _write_status(run_paths, "running", [])

    run_id = run_paths.root.name
    with _jobs_lock:
        _jobs[run_id] = JobHandle(run_id, run_paths, proc)

    threading.Thread(target=_watch, args=(run_id, run_paths, proc), daemon=True).start()
    return run_id


def confirm_login(run_paths: RunPaths) -> None:
    """Write the control file that unblocks FileInteractionHandler.await_login
    (see interaction.py) — called by POST /api/runs/{id}/login-complete."""
    ack_path = run_paths.login_ack_json()
    ack_path.parent.mkdir(parents=True, exist_ok=True)
    ack_path.write_text(json.dumps({"confirmed_at": time.time()}), encoding="utf-8")


def run_retry_sync(
    run_paths: RunPaths, citation_id: str, override_url: Optional[str], timeout: float = 180.0
) -> dict:
    """
    Run scripts/revalidate_citation.py (B5) synchronously and return its raw
    outcome. Blocking is deliberate: a retry is a single citation batch (one
    download + a handful of LLM calls), the frontend shows a spinner, and the
    caller needs the fresh result immediately to update the UI — no polling
    protocol is worth building for a call that normally finishes in seconds.
    """
    args = [sys.executable, str(_RETRY_SCRIPT), str(run_paths.root), citation_id]
    if override_url:
        args.append(override_url)
    result = subprocess.run(
        args, cwd=str(_PROJECT_ROOT), capture_output=True, text=True, timeout=timeout
    )
    return {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
