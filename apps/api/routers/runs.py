"""Run lifecycle: list, create, detail, delete, live events, login handoff,
and the cross-run compare endpoint (S1, S2, S7, S8, §8, §11)."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from apps.api.deps import get_run_paths
from apps.api.schemas import (
    CompareResult, CompareRow, ReferenceCheckRow, RunCreateResponse, RunDetail,
    RunSummaryRow,
)
from apps.api.services import job_manager, read_model, run_registry
from apps.api.services.event_stream import stream_run_events
from asv.core.run_paths import RunPaths

router = APIRouter(prefix="/api", tags=["runs"])

PDFS_DIR = Path("pdfs")


@router.get("/runs", response_model=List[RunSummaryRow])
def list_runs() -> List[RunSummaryRow]:
    return run_registry.list_runs()


@router.post("/runs", response_model=RunCreateResponse)
async def create_run(
    pdf: Optional[UploadFile] = File(None),
    pdf_path: Optional[str] = Form(None),
) -> RunCreateResponse:
    """Launch a new run. Provide either a multipart PDF upload (``pdf``) or
    the server-local path to an existing PDF (``pdf_path``, e.g. under pdfs/)."""
    if pdf is not None:
        PDFS_DIR.mkdir(parents=True, exist_ok=True)
        dest = PDFS_DIR / pdf.filename
        content = await pdf.read()
        dest.write_bytes(content)
        target_path = str(dest)
    elif pdf_path:
        target_path = pdf_path
        if not Path(target_path).exists():
            raise HTTPException(status_code=400, detail=f"PDF not found: {target_path}")
    else:
        raise HTTPException(status_code=400, detail="Provide either a pdf upload or pdf_path")

    run_id = job_manager.launch_run(target_path)
    return RunCreateResponse(run_id=run_id)


@router.get("/pdfs", response_model=List[str])
def list_pdfs() -> List[str]:
    if not PDFS_DIR.exists():
        return []
    return sorted(p.name for p in PDFS_DIR.glob("*.pdf"))


@router.get("/runs/{run_id}", response_model=RunDetail)
def get_run(run_paths: RunPaths = Depends(get_run_paths)) -> RunDetail:
    return run_registry.get_run_detail(run_paths)


@router.get("/runs/{run_id}/references", response_model=List[ReferenceCheckRow])
def list_references(run_paths: RunPaths = Depends(get_run_paths)) -> List[ReferenceCheckRow]:
    """Tier 0.6 bibliography audit: every reference in the paper, whether it was
    found in the free indexes, and whether it has been retracted.

    Empty for runs made before the audit existed."""
    return run_registry.list_reference_checks(run_paths)


@router.delete("/runs/{run_id}")
def delete_run(run_paths: RunPaths = Depends(get_run_paths)) -> dict:
    run_registry.delete_run(run_paths.root)
    return {"ok": True}


@router.get("/runs/{run_id}/events")
async def run_events(request: Request, run_paths: RunPaths = Depends(get_run_paths)):
    async def is_disconnected() -> bool:
        return await request.is_disconnected()

    return StreamingResponse(
        stream_run_events(run_paths, is_disconnected),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/runs/{run_id}/login-complete")
def login_complete(run_paths: RunPaths = Depends(get_run_paths)) -> dict:
    """Unblocks FileInteractionHandler.await_login (§8) for a paused run."""
    job_manager.confirm_login(run_paths)
    return {"ok": True}


@router.get("/compare", response_model=CompareResult)
def compare_runs(a: str, b: str) -> CompareResult:
    run_a = get_run_paths(a)
    run_b = get_run_paths(b)
    rows_a = {r.claim_id: r for r in read_model.build_claim_rows(run_a)}
    rows_b = {r.claim_id: r for r in read_model.build_claim_rows(run_b)}

    rows: List[CompareRow] = []
    for claim_id in sorted(set(rows_a) | set(rows_b)):
        ra, rb = rows_a.get(claim_id), rows_b.get(claim_id)
        text = (ra or rb).text  # type: ignore[union-attr]
        av = ra.result.verdict if ra and ra.result else None
        ac = ra.result.confidence if ra and ra.result else None
        bv = rb.result.verdict if rb and rb.result else None
        bc = rb.result.confidence if rb and rb.result else None
        rows.append(CompareRow(
            claim_id=claim_id, text=text,
            a_verdict=av, a_confidence=ac, b_verdict=bv, b_confidence=bc,
            changed=av != bv,
        ))

    return CompareResult(run_a=a, run_b=b, rows=rows)
