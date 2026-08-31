"""Original PDF bytes + highlight quads (S5, §7)."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from api.deps import get_run_paths
from api.schemas import HighlightQuad
from api.services import pdf_highlights, read_model
from models import ClaimObject
from run_paths import RunPaths

router = APIRouter(prefix="/api", tags=["paper"])

PDFS_DIR = Path("pdfs")


def _find_original_pdf(run_paths: RunPaths) -> Optional[Path]:
    candidate = PDFS_DIR / f"{run_paths.pdf_stem}.pdf"
    if candidate.exists():
        return candidate
    if PDFS_DIR.exists():
        for p in PDFS_DIR.glob("*.pdf"):
            if p.stem == run_paths.pdf_stem:
                return p
    return None


@router.get("/runs/{run_id}/paper.pdf")
def get_paper_pdf(run_paths: RunPaths = Depends(get_run_paths)):
    pdf_path = _find_original_pdf(run_paths)
    if pdf_path is None:
        raise HTTPException(status_code=404, detail="Original PDF not found in pdfs/")
    return FileResponse(str(pdf_path), media_type="application/pdf", filename=pdf_path.name)


@router.get("/runs/{run_id}/highlights", response_model=List[HighlightQuad])
def get_highlights(run_paths: RunPaths = Depends(get_run_paths)) -> List[HighlightQuad]:
    pdf_path = _find_original_pdf(run_paths)
    if pdf_path is None:
        raise HTTPException(status_code=404, detail="Original PDF not found in pdfs/")

    claims_data = read_model.load_json(run_paths.claims_json(), {"claims": []})
    claims = [ClaimObject(**c) for c in claims_data.get("claims", [])]
    raw = pdf_highlights.resolve_highlights(run_paths, pdf_path, claims)
    return [HighlightQuad(**r) for r in raw]
