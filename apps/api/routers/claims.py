"""Normalized claim queries — the workhorse endpoints for S3 (claims explorer)
and S4 (claim detail)."""

from __future__ import annotations

from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from apps.api.deps import get_run_paths
from apps.api.schemas import ClaimDetail, ClaimRow, ClaimsPage
from apps.api.services import read_model
from asv.core.run_paths import RunPaths

router = APIRouter(prefix="/api", tags=["claims"])


def _compute_facets(rows: List[ClaimRow]) -> Dict[str, Dict[str, int]]:
    """Facet counts over the full (unfiltered) row set — cheap, and lets the
    UI show "233" next to a filter chip whether or not it's currently applied."""
    facets: Dict[str, Dict[str, int]] = {
        "group": {}, "verdict": {}, "claim_type": {}, "method": {},
        # Tier 0.2: the reason is what tells a reader what to do about an
        # abstention, so it gets its own filter rather than being buried in
        # thirteen verdict values.
        "not_checkable_reason": {}, "flag": {},
    }
    for r in rows:
        facets["group"][r.group] = facets["group"].get(r.group, 0) + 1
        facets["claim_type"][r.claim_type] = facets["claim_type"].get(r.claim_type, 0) + 1
        if r.result:
            v = r.result.verdict.value
            facets["verdict"][v] = facets["verdict"].get(v, 0) + 1
            facets["method"][r.result.method] = facets["method"].get(r.result.method, 0) + 1
            if r.result.not_checkable_reason is not None:
                k = r.result.not_checkable_reason.value
                facets["not_checkable_reason"][k] = facets["not_checkable_reason"].get(k, 0) + 1
            for flag in r.result.flags:
                facets["flag"][flag] = facets["flag"].get(flag, 0) + 1
    return facets


@router.get("/runs/{run_id}/claims", response_model=ClaimsPage)
def list_claims(
    run_paths: RunPaths = Depends(get_run_paths),
    group: Optional[str] = None,
    verdict: Optional[str] = None,
    not_checkable_reason: Optional[str] = None,
    flag: Optional[str] = None,
    claim_type: Optional[str] = None,
    method: Optional[str] = None,
    has_evidence: Optional[bool] = None,
    citation_id: Optional[str] = None,
    is_original: Optional[bool] = None,
    originally_uncited: Optional[bool] = None,
    min_confidence: Optional[float] = None,
    max_confidence: Optional[float] = None,
    q: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
) -> ClaimsPage:
    rows = read_model.build_claim_rows(run_paths)
    facets = _compute_facets(rows)

    def matches(r: ClaimRow) -> bool:
        if group and r.group != group:
            return False
        if verdict and (r.result is None or r.result.verdict.value != verdict):
            return False
        if not_checkable_reason and (
            r.result is None
            or r.result.not_checkable_reason is None
            or r.result.not_checkable_reason.value != not_checkable_reason
        ):
            return False
        if flag and (r.result is None or flag not in r.result.flags):
            return False
        if has_evidence is not None and (
            r.result is None or bool(r.result.evidence) != has_evidence
        ):
            return False
        if claim_type and r.claim_type != claim_type:
            return False
        if method and (r.result is None or r.result.method != method):
            return False
        if citation_id and (r.citation is None or r.citation.id != citation_id):
            return False
        if is_original is not None and r.is_original != is_original:
            return False
        if originally_uncited is not None and r.originally_uncited != originally_uncited:
            return False
        if min_confidence is not None and (r.result is None or r.result.confidence < min_confidence):
            return False
        if max_confidence is not None and (r.result is None or r.result.confidence > max_confidence):
            return False
        if q:
            ql = q.lower()
            hay = r.text.lower()
            if r.citation and r.citation.raw_text:
                hay += " " + r.citation.raw_text.lower()
            if ql not in hay:
                return False
        return True

    filtered = [r for r in rows if matches(r)]
    total = len(filtered)
    start = (page - 1) * page_size
    page_rows = filtered[start:start + page_size]

    return ClaimsPage(claims=page_rows, total=total, facets=facets)


@router.get("/runs/{run_id}/claims/{claim_id}", response_model=ClaimDetail)
def get_claim(claim_id: str, run_paths: RunPaths = Depends(get_run_paths)) -> ClaimDetail:
    row = read_model.get_claim_row(run_paths, claim_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}")

    siblings = read_model.get_sibling_rows(run_paths, row)

    script_source = None
    if row.generated_script_path:
        script_file = run_paths.root / row.generated_script_path
        if script_file.exists():
            script_source = script_file.read_text(encoding="utf-8", errors="replace")

    return ClaimDetail(
        **row.model_dump(),
        raw_citation_text=row.citation.raw_text if row.citation else None,
        generated_script_source=script_source,
        sibling_claims=siblings,
    )
