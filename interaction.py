"""Interaction handoff for the one blocking human checkpoint in the pipeline:
paywall login.

``ClaimOrchestrator._setup_browser_searcher`` used to print instructions and
call bare ``input()`` — fine for a CLI, impossible for a web backend (stdin on
a FastAPI worker is not a human). This module replaces that with a small
``InteractionHandler`` seam so the *same* orchestrator code drives both:

- ``ConsoleInteractionHandler`` (default) reproduces the exact original
  behavior — CLI runs via ``scripts/run_pipeline.py`` are unaffected.
- ``FileInteractionHandler`` is used by the web backend's job runner: it
  emits an ``awaiting_login`` event to ``events.jsonl`` and polls a control
  file instead of blocking on stdin. See docs/FRONTEND_PLAN.md §8.
"""

from __future__ import annotations

import logging
import time
from typing import List, Protocol

from run_paths import RunPaths

logger = logging.getLogger(__name__)


class InteractionHandler(Protocol):
    """The single checkpoint the orchestrator needs from whoever drives it."""

    def await_login(self, domains: List[str]) -> None:
        """Block until the user has logged in to ``domains`` in the open browser."""
        ...


class ConsoleInteractionHandler:
    """Default handler — reproduces the pipeline's original CLI behavior exactly."""

    def await_login(self, domains: List[str]) -> None:
        print(
            f"\n[ASV] Please log in to the following sites in the browser window:\n"
            f"  {', '.join(domains)}\n"
            "Press Enter here when done to continue the pipeline..."
        )
        input()
        logger.info("User completed login — continuing pipeline")


class FileInteractionHandler:
    """
    Web-driven handler: emits an ``awaiting_login`` event, then polls a
    control file (``control/login_ack.json``) instead of blocking on stdin.
    The API's ``POST /api/runs/{id}/login-complete`` writes that file when the
    user confirms they've finished logging in in the (server-local) browser
    window Playwright opened.

    Times out after ``timeout_seconds`` (default 15 min) and proceeds without
    the login rather than hanging a job forever.
    """

    def __init__(
        self,
        run_paths: RunPaths,
        event_logger,
        timeout_seconds: float = 900.0,
        poll_interval: float = 0.5,
    ):
        self.run_paths = run_paths
        self.event_logger = event_logger
        self.timeout_seconds = timeout_seconds
        self.poll_interval = poll_interval

    def await_login(self, domains: List[str]) -> None:
        ack_path = self.run_paths.login_ack_json()
        ack_path.parent.mkdir(parents=True, exist_ok=True)
        # Clear a stale ack from an earlier checkpoint on this same run folder.
        # Timestamped run folders are normally one-shot, but a citation retry
        # (revalidate_citation) can reuse one.
        try:
            ack_path.unlink(missing_ok=True)  # type: ignore[call-arg]
        except Exception:
            pass

        logger.info(f"Awaiting login for domains: {domains} (write {ack_path} to continue)")
        self.event_logger.emit("awaiting_login", domains=domains)

        deadline = time.time() + self.timeout_seconds
        while not ack_path.exists():
            if time.time() > deadline:
                logger.warning(
                    f"Login wait timed out after {self.timeout_seconds}s — continuing without it"
                )
                self.event_logger.emit("login_timeout", domains=domains)
                return
            time.sleep(self.poll_interval)

        logger.info("Login acknowledgement received — continuing pipeline")
        self.event_logger.emit("login_complete", domains=domains)
