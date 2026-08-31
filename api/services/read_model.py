"""The 4-file (+ manifests) → ``ClaimRow[]`` normalizer — docs/FRONTEND_PLAN.md §5.2.

The four validation-result files are not homogeneous (§2.1): the two
``*_uncited_results.json`` files are ``List[ValidationResult]``, the two
``*_cited_results.json`` files are ``List[ValidationBatch]`` wrapping
``claim_results``. This module is the *only* place that shape split is
allowed to matter — everything downstream (routers, frontend) sees a flat
``ClaimRow`` list.

``verdict`` is the key derived field. ``passed`` alone conflates "the source
was obtained and the claim did not hold up" with "we never got the source" —
splitting them (``unresolved_source`` as a third state) is what makes the
qual-cited/quant-cited failure rates in a typical run honest.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from models import ClaimObject
from run_paths import RunPaths

from api.schemas import BatchRef, CitationRef, ClaimRow, LocationRef, ResultRef

_RESULT_FILES: Dict[str, str] = {
    "qual_uncited": "qualitative_uncited_results.json",
    "quant_uncited": "quantitative_uncited_results.json",
    "qual_cited": "qualitative_cited_results.json",
    "quant_cited": "quantitative_cited_results.json",
}

_lock = threading.Lock()
_cache: Dict[str, Tuple[float, List[ClaimRow]]] = {}


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _combined_mtime(run_paths: RunPaths) -> float:
    paths = [run_paths.claims_json()] + [
        run_paths.validation_results / fname for fname in _RESULT_FILES.values()
    ]
    return max((_mtime(p) for p in paths), default=0.0)


def _derive_verdict(method: str, passed: bool, batch_download_successful: Optional[bool]) -> str:
    if method == "source_not_found":
        return "unresolved_source"
    if batch_download_successful is False:
        return "unresolved_source"
    return "passed" if passed else "failed"


def load_manifest_by_citation(path: Path) -> Dict[str, dict]:
    """Return {citation_id: entry_dict}, last entry wins for a repeated id
    (a retry via revalidate_citation appends rather than replaces)."""
    data = load_json(path, {})
    entries = data.get("entries", []) if isinstance(data, dict) else []
    out: Dict[str, dict] = {}
    for e in entries:
        cid = e.get("citation_id")
        if cid is not None:
            out[str(cid)] = e
    return out


def _result_ref(
    *, method: str, confidence: float, passed: bool, explanation: str,
    errors: Optional[str], sources_used: List[str], validated_at: Optional[str],
    validation_metadata: Optional[dict], batch_download_successful: Optional[bool],
) -> ResultRef:
    return ResultRef(
        verdict=_derive_verdict(method, passed, batch_download_successful),
        passed=passed,
        confidence=confidence,
        method=method,
        explanation=explanation,
        errors=errors,
        sources_used=sources_used or [],
        validated_at=validated_at,
        validation_metadata=validation_metadata,
    )


def _script_path_for(run_paths: RunPaths, claim_id: str) -> Optional[str]:
    p = run_paths.generated_scripts / f"validate_{claim_id}.py"
    if p.exists():
        return f"generated_scripts/validate_{claim_id}.py"
    return None


def build_claim_rows(run_paths: RunPaths, *, use_cache: bool = True) -> List[ClaimRow]:
    """Build the full, cached ``ClaimRow[]`` for one run."""
    run_id = run_paths.root.name
    mtime = _combined_mtime(run_paths)

    if use_cache:
        with _lock:
            cached = _cache.get(run_id)
            if cached is not None and cached[0] == mtime:
                return cached[1]

    claims_data = load_json(run_paths.claims_json(), {"claims": [], "citations": {}})
    claims = [ClaimObject(**c) for c in claims_data.get("claims", [])]
    citations: Dict[str, str] = claims_data.get("citations", {})

    dataset_manifest = load_manifest_by_citation(run_paths.datasets_manifest_json())
    text_manifest = load_manifest_by_citation(run_paths.text_sources_manifest_json())

    # index: claim_id -> (group, ResultRef, BatchRef or None)
    index: Dict[str, Tuple[str, ResultRef, Optional[BatchRef]]] = {}

    for group, fname in _RESULT_FILES.items():
        raw = load_json(run_paths.validation_results / fname, [])
        is_cited = group.endswith("_cited")

        if not is_cited:
            for r in raw:
                result = _result_ref(
                    method=r.get("validation_method", ""),
                    confidence=r.get("confidence", 0.0),
                    passed=r.get("passed", False),
                    explanation=r.get("explanation", ""),
                    errors=r.get("errors"),
                    sources_used=r.get("sources_used", []),
                    validated_at=r.get("validated_at"),
                    validation_metadata=r.get("validation_metadata"),
                    batch_download_successful=None,
                )
                index[r["claim_id"]] = (group, result, None)
        else:
            manifest = dataset_manifest if group == "quant_cited" else text_manifest
            for batch in raw:
                claim_results = batch.get("claim_results", [])
                sibling_ids = [cr["claim_id"] for cr in claim_results]
                manifest_entry = manifest.get(str(batch.get("citation_id")), {})
                batch_ref = BatchRef(
                    citation_id=str(batch.get("citation_id")),
                    download_successful=bool(batch.get("download_successful")),
                    winning_url=batch.get("source_url") or manifest_entry.get("winning_url"),
                    format=manifest_entry.get("format"),
                    resolution_attempts=batch.get("resolution_attempts", []),
                    notes=batch.get("batch_notes", ""),
                    sibling_claim_ids=sibling_ids,
                )
                for cr in claim_results:
                    result = _result_ref(
                        method=cr.get("validation_method", ""),
                        confidence=cr.get("confidence", 0.0),
                        passed=cr.get("passed", False),
                        explanation=cr.get("explanation", ""),
                        errors=cr.get("errors"),
                        sources_used=cr.get("sources_used", []),
                        validated_at=cr.get("validated_at"),
                        validation_metadata=cr.get("validation_metadata"),
                        batch_download_successful=batch.get("download_successful"),
                    )
                    index[cr["claim_id"]] = (group, result, batch_ref)

    rows: List[ClaimRow] = []
    for claim in claims:
        entry = index.get(claim.claim_id)
        if entry is not None:
            group, result, batch = entry
        else:
            # Present in claims.json but absent from every result file —
            # dropped by routing (§13 normalizer edge case). Best-guess the
            # group from the claim's own type/citation fields so it still
            # sorts sensibly, but mark it unmistakably as unvalidated.
            if claim.claim_type == "qualitative":
                group = "qual_cited" if claim.citation_id else "qual_uncited"
            else:
                group = "quant_cited" if claim.citation_id else "quant_uncited"
            result = None
            batch = None

        citation_ref: Optional[CitationRef] = None
        if claim.citation_id or claim.citation_text or claim.citation_details:
            raw_text = citations.get(claim.citation_id or "") if claim.citation_id else None
            if not raw_text and claim.citation_details:
                raw_text = claim.citation_details.raw_text
            citation_ref = CitationRef(
                id=claim.citation_id,
                marker=claim.citation_text,
                raw_text=raw_text,
                details=claim.citation_details,
            )

        location_ref = None
        if claim.location_in_text is not None:
            location_ref = LocationRef(
                start=claim.location_in_text.start,
                end=claim.location_in_text.end,
                chunk_id=claim.location_in_text.chunk_id,
            )

        script_path = None
        if claim.claim_type == "quantitative":
            script_path = _script_path_for(run_paths, claim.claim_id)

        rows.append(ClaimRow(
            claim_id=claim.claim_id,
            text=claim.text,
            claim_type=claim.claim_type,
            group=group,  # type: ignore[arg-type]
            is_original=claim.is_original,
            originally_uncited=claim.originally_uncited,
            found_source=claim.found_source,
            citation=citation_ref,
            location_in_text=location_ref,
            result=result if result is not None else _skipped_result(),
            batch=batch,
            generated_script_path=script_path,
        ))

    if use_cache:
        with _lock:
            _cache[run_id] = (mtime, rows)

    return rows


def _skipped_result() -> ResultRef:
    return ResultRef(
        verdict="skipped", passed=False, confidence=0.0, method="not_validated",
        explanation="Claim was extracted but never reached a validation step.",
    )


def get_claim_row(run_paths: RunPaths, claim_id: str) -> Optional[ClaimRow]:
    for row in build_claim_rows(run_paths):
        if row.claim_id == claim_id:
            return row
    return None


def get_sibling_rows(run_paths: RunPaths, row: ClaimRow) -> List[ClaimRow]:
    if row.batch is None:
        return []
    ids = set(row.batch.sibling_claim_ids) - {row.claim_id}
    return [r for r in build_claim_rows(run_paths) if r.claim_id in ids]
