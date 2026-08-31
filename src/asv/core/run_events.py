"""Machine-readable per-run progress channel — ``logs/events.jsonl``.

Complements the existing human-readable ``orchestration.log``. Each event is
one JSON object per line, appended as validation proceeds, so a web frontend
(or ``tail -f``) can show live progress without parsing log prose.

This is additive: ``ClaimOrchestrator`` always creates a ``RunEventLogger``
and emits to it, for both CLI and API-driven runs. Writing the file costs one
disk append per event and has no effect on the existing ``orchestration.log``
or the four validation-result JSON files.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from asv.core.run_paths import RunPaths

logger = logging.getLogger(__name__)


class RunEventLogger:
    """Append-only JSONL writer for one run's ``logs/events.jsonl``."""

    def __init__(self, run_paths: RunPaths):
        self.path: Path = run_paths.events_jsonl()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def emit(self, event_type: str, **fields: Any) -> None:
        """Append one event. Never raises — a logging failure must not break
        the pipeline it's observing."""
        record = {"ts": datetime.now().isoformat(), "type": event_type, **fields}
        try:
            line = json.dumps(record, ensure_ascii=False, default=str)
        except Exception as e:
            logger.warning(f"Failed to serialize event {event_type!r}: {e}")
            return
        try:
            with self._lock:
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
        except Exception as e:
            logger.warning(f"Failed to write event {event_type!r} to {self.path}: {e}")
