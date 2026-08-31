"""Fixtures for api/ tests.

Uses the committed `runs/hsv_cancer__*` folders as golden fixture data
(docs/FRONTEND_PLAN.md §13) — real heterogeneous output: successful batches,
failed batches, empty resolution_attempts, null citation_details. No mocking
needed since it's all static JSON already on disk.
"""

import pytest

from run_paths import RunPaths, RUNS_ROOT_DIR
from pathlib import Path

_KNOWN_RUN = "hsv_cancer__20260706_192057"


@pytest.fixture
def sample_run_paths() -> RunPaths:
    run_dir = Path(RUNS_ROOT_DIR) / _KNOWN_RUN
    if not run_dir.is_dir():
        pytest.skip(f"fixture run folder not present: {run_dir}")
    return RunPaths.from_existing(run_dir)


@pytest.fixture
def all_run_dirs():
    root = Path(RUNS_ROOT_DIR)
    if not root.is_dir():
        pytest.skip("runs/ not present")
    dirs = sorted(p for p in root.iterdir() if p.is_dir() and "__" in p.name)
    if not dirs:
        pytest.skip("no run folders present under runs/")
    return dirs
