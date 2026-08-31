"""Shared FastAPI dependencies."""

from __future__ import annotations

from fastapi import HTTPException

from apps.api.services.run_registry import runs_root
from asv.core.run_paths import RunPaths


def get_run_paths(run_id: str) -> RunPaths:
    """Resolve a run_id (the run folder's own name) to RunPaths, or 404."""
    run_dir = runs_root() / run_id
    if not run_dir.is_dir() or "__" not in run_dir.name:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    try:
        return RunPaths.from_existing(run_dir)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
