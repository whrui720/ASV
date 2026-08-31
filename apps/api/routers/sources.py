"""Source manifests + per-citation retry (S6, B5)."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException

from apps.api.deps import get_run_paths
from apps.api.schemas import RetryRequest, RetryResponse, SourceRow
from apps.api.services import job_manager, read_model
from asv.core.run_paths import RunPaths

router = APIRouter(prefix="/api", tags=["sources"])


@router.get("/runs/{run_id}/sources", response_model=List[SourceRow])
def list_sources(run_paths: RunPaths = Depends(get_run_paths)) -> List[SourceRow]:
    rows: List[SourceRow] = []
    manifests = (
        ("dataset", run_paths.datasets_manifest_json()),
        ("text", run_paths.text_sources_manifest_json()),
    )
    for kind, path in manifests:
        for cid, e in read_model.load_manifest_by_citation(path).items():
            rows.append(SourceRow(
                kind=kind,  # type: ignore[arg-type]
                citation_id=cid,
                citation_text=e.get("citation_text"),
                raw_citation_text=e.get("raw_citation_text"),
                citation_details=e.get("citation_details"),
                resolution_attempts=e.get("resolution_attempts", []),
                winning_url=e.get("winning_url"),
                format=e.get("format"),
                filename=e.get("filename"),
                downloaded_at=e.get("downloaded_at"),
                deleted_at=e.get("deleted_at"),
                batch_num_claims=e.get("batch_num_claims", 0),
                batch_download_successful=e.get("batch_download_successful", False),
            ))
    return rows


@router.post("/runs/{run_id}/sources/{citation_id}/retry", response_model=RetryResponse)
def retry_citation(
    citation_id: str, body: RetryRequest, run_paths: RunPaths = Depends(get_run_paths)
) -> RetryResponse:
    outcome = job_manager.run_retry_sync(run_paths, citation_id, body.override_url)
    if outcome["returncode"] != 0:
        raise HTTPException(status_code=500, detail=f"Retry failed: {outcome['stderr'][-2000:]}")

    rows = read_model.build_claim_rows(run_paths, use_cache=False)
    matching = [r for r in rows if r.citation and r.citation.id == citation_id]
    if not matching:
        raise HTTPException(status_code=404, detail=f"No claims found for citation_id={citation_id}")

    batch = matching[0].batch
    return RetryResponse(
        citation_id=citation_id,
        download_successful=bool(batch.download_successful) if batch else False,
        num_claims=len(matching),
        job_id=f"retry_{citation_id}",
    )
