"""Server-Sent Events tail of ``events.jsonl`` + ``orchestration.log`` for one run.

One-directional server→client streaming (§4: "simpler than WebSockets and
enough for logs + progress"). Replays everything already on disk from offset
0, then polls for new lines — a client that opens the stream after the run
already started still sees full history, not just what's appended from then on.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import AsyncIterator, Awaitable, Callable

from asv.core.run_paths import RunPaths


def _sse(event_type: str, data: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def stream_run_events(
    run_paths: RunPaths,
    is_disconnected: Callable[[], Awaitable[bool]],
    poll_interval: float = 0.75,
    idle_timeout: float = 3600.0,
) -> AsyncIterator[str]:
    """
    Yields SSE-formatted strings: ``event: progress`` per events.jsonl record,
    ``event: log`` per new orchestration.log line, and a final ``event:
    terminal`` when the run reaches complete/failed, the client disconnects,
    or `idle_timeout` elapses (safety net against an abandoned connection
    outliving a crashed subprocess that never wrote a terminal status).
    """
    events_path = run_paths.events_jsonl()
    log_path = run_paths.orchestration_log()
    status_path = run_paths.status_json()

    events_offset = 0
    log_offset = 0
    started = time.time()

    while True:
        if await is_disconnected():
            return

        if events_path.exists():
            with open(events_path, "r", encoding="utf-8", errors="replace") as f:
                f.seek(events_offset)
                new_lines = f.readlines()
                events_offset = f.tell()
            for line in new_lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                yield _sse("progress", payload)

        if log_path.exists():
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                f.seek(log_offset)
                new_log_lines = f.readlines()
                log_offset = f.tell()
            for line in new_log_lines:
                line = line.rstrip("\n")
                if line:
                    yield _sse("log", {"line": line})

        status_value = None
        if status_path.exists():
            try:
                status_value = json.loads(status_path.read_text(encoding="utf-8")).get("status")
            except Exception:
                pass
        elif run_paths.run_summary_json().exists():
            status_value = "complete"

        if status_value in ("complete", "failed"):
            yield _sse("terminal", {"status": status_value})
            return

        if time.time() - started > idle_timeout:
            yield _sse("terminal", {"status": "timeout"})
            return

        await asyncio.sleep(poll_interval)
