"""The 4-file (+ manifests) → ``ClaimRow[]`` normalizer — docs/FRONTEND_PLAN.md §5.2.

The four validation-result files are not homogeneous (§2.1): the two
``*_uncited_results.json`` files are ``List[ValidationResult]``, the two
``*_cited_results.json`` files are ``List[ValidationBatch]`` wrapping
``claim_results``. This module is the *only* place that shape split is
allowed to matter — everything downstream (routers, frontend) sees a flat
``ClaimRow`` list.

Since Tier 0.2, ``verdict`` is **not** derived here — the pipeline persists it
at judgment time, because the distinctions that matter (contradicted vs merely
unsupported; paywalled vs abstract-only vs never-resolved) are only knowable
where the judgment happens and are destroyed by the time a result file is read.

What remains here is the *legacy* path: eight run folders predate Tier 0 and
are the evidence base for the project's published numbers, so they are never
rewritten. Any result entry without a ``verdict`` key is mapped onto the new
ontology on read and flagged ``legacy: true`` so the UI can badge it.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from asv.core.models import ClaimObject, ReferenceCheck, RESULT_SCHEMA_VERSION
from asv.core.run_paths import RunPaths
from asv.core.verdicts import ContentQuality, NotCheckableReason, Verdict

from apps.api.schemas import BatchRef, CitationRef, ClaimRow, LocationRef, ResultRef

#: Legacy ``validation_method`` values whose results came from asking a model
#: whether a sentence sounded plausible. On the reference run these accounted
#: for 247 of 306 claims and 217 of 224 "passes", with ``sources_used: []``.
#: Rendering them as ``substantiated`` would reproduce, in the new UI, exactly
#: the claim Tier 0 exists to stop making — so they read as abstentions, with
#: the original boolean preserved in ``validation_metadata.legacy_passed``.
_LEGACY_PLAUSIBILITY_METHODS = frozenset({
    "truth_table+llm_check", "truth_table+llm_only", "llm_check",
})

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
    paths = [run_paths.claims_json(), run_paths.reference_checks_json()] + [
        run_paths.validation_results / fname for fname in _RESULT_FILES.values()
    ]
    return max((_mtime(p) for p in paths), default=0.0)


def schema_version(run_paths: RunPaths) -> int:
    """1 for pre-Tier-0 run folders, 2 once verdicts are persisted."""
    marker = load_json(run_paths.results_schema_json(), None)
    if isinstance(marker, dict):
        try:
            return int(marker.get("schema_version", 1))
        except (TypeError, ValueError):
            return 1
    return 1


def _legacy_verdict(
    method: str, passed: bool, batch_download_successful: Optional[bool]
) -> Tuple[Verdict, Optional[NotCheckableReason]]:
    """Map a pre-Tier-0 result onto the current ontology.

    Deliberately conservative in one place: rows produced by the plausibility
    path become abstentions rather than ``substantiated``, because that is what
    they actually were. The raw run files are untouched — this only changes how
    a historical run renders, and it renders behind a "legacy run" badge.
    """
    if method in _LEGACY_PLAUSIBILITY_METHODS:
        return Verdict.NOT_CHECKABLE, NotCheckableReason.NO_SOURCE_AVAILABLE
    if method == "source_not_found":
        return Verdict.NOT_CHECKABLE, NotCheckableReason.SOURCE_NOT_RESOLVED
    if batch_download_successful is False:
        return Verdict.NOT_CHECKABLE, NotCheckableReason.SOURCE_DOWNLOAD_FAILED
    if passed:
        return Verdict.SUBSTANTIATED, None
    return Verdict.NOT_SUBSTANTIATED, None


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


def _result_ref(entry: dict, batch_download_successful: Optional[bool]) -> ResultRef:
    """Normalise one raw result entry, whichever schema wrote it."""
    method = entry.get("validation_method", "")
    metadata = entry.get("validation_metadata")

    if "verdict" in entry:
        verdict = Verdict(entry["verdict"])
        raw_reason = entry.get("not_checkable_reason")
        reason = NotCheckableReason(raw_reason) if raw_reason else None
        confidence = entry.get("confidence")
        legacy = False
    else:
        passed = bool(entry.get("passed", False))
        verdict, reason = _legacy_verdict(method, passed, batch_download_successful)
        # A confidence that belonged to a verdict we have just downgraded to an
        # abstention would be actively misleading, so it is dropped from the
        # rendered row and preserved in metadata instead.
        confidence = None if verdict == Verdict.NOT_CHECKABLE else entry.get("confidence")
        metadata = dict(metadata or {})
        metadata["legacy_passed"] = passed
        metadata["legacy_confidence"] = entry.get("confidence")
        legacy = True

    raw_quality = entry.get("content_quality")
    return ResultRef(
        verdict=verdict,
        not_checkable_reason=reason,
        passed=(verdict == Verdict.SUBSTANTIATED),
        confidence=confidence,
        method=method,
        explanation=entry.get("explanation", ""),
        evidence=entry.get("evidence", []) or [],
        source_url=entry.get("source_url"),
        content_quality=ContentQuality(raw_quality) if raw_quality else None,
        flags=entry.get("flags", []) or [],
        errors=entry.get("errors"),
        sources_used=entry.get("sources_used", []) or [],
        validated_at=entry.get("validated_at"),
        validation_metadata=metadata,
        legacy=legacy,
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
    ref_checks = load_reference_checks(run_paths)

    # index: claim_id -> (group, ResultRef, BatchRef or None)
    index: Dict[str, Tuple[str, ResultRef, Optional[BatchRef]]] = {}

    for group, fname in _RESULT_FILES.items():
        raw = load_json(run_paths.validation_results / fname, [])
        is_cited = group.endswith("_cited")

        if not is_cited:
            for r in raw:
                index[r["claim_id"]] = (group, _result_ref(r, None), None)
        else:
            manifest = dataset_manifest if group == "quant_cited" else text_manifest
            for batch in raw:
                claim_results = batch.get("claim_results", [])
                sibling_ids = [cr["claim_id"] for cr in claim_results]
                manifest_entry = manifest.get(str(batch.get("citation_id")), {})
                raw_quality = (
                    batch.get("content_quality") or manifest_entry.get("content_quality")
                )
                batch_ref = BatchRef(
                    citation_id=str(batch.get("citation_id")),
                    download_successful=bool(batch.get("download_successful")),
                    judgeable=bool(
                        batch.get("judgeable", manifest_entry.get("batch_judgeable", False))
                    ),
                    content_quality=ContentQuality(raw_quality) if raw_quality else None,
                    winning_url=batch.get("source_url") or manifest_entry.get("winning_url"),
                    format=manifest_entry.get("format"),
                    resolution_attempts=batch.get("resolution_attempts", []),
                    reference_check=(
                        ReferenceCheck(**batch["reference_check"])
                        if batch.get("reference_check") else
                        ref_checks.get(str(batch.get("citation_id")))
                    ),
                    notes=batch.get("batch_notes", ""),
                    sibling_claim_ids=sibling_ids,
                )
                for cr in claim_results:
                    result = _result_ref(cr, batch.get("download_successful"))
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
    """A claim present in claims.json but absent from every result file."""
    return ResultRef(
        verdict=Verdict.NOT_CHECKABLE,
        not_checkable_reason=NotCheckableReason.VALIDATION_ERROR,
        passed=False, confidence=None, method="not_validated",
        explanation="Claim was extracted but never reached a validation step.",
    )


def load_reference_checks(run_paths: RunPaths) -> Dict[str, ReferenceCheck]:
    """Tier 0.6 bibliography audit, keyed by citation_id. Empty for old runs."""
    data = load_json(run_paths.reference_checks_json(), {})
    out: Dict[str, ReferenceCheck] = {}
    for raw in (data.get("checks", []) if isinstance(data, dict) else []):
        try:
            check = ReferenceCheck(**raw)
        except Exception:
            continue
        out[str(check.citation_id)] = check
    return out


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
