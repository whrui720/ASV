"""API-facing Pydantic models.

Reuses ``models.py`` (the pipeline's own Pydantic v2 models) wherever a field
shape already matches — ``CitationDetails``, ``ResolutionAttempt``,
``FoundDatasetSource`` are used verbatim as nested types. New models here are
strictly the *read model* (docs/FRONTEND_PLAN.md §5.2): the normalized,
frontend-facing shape that hides the two-shape trap in the raw result files.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from asv.core.models import (
    CitationDetails, EvidenceSpan, FoundDatasetSource, ReferenceCheck, ResolutionAttempt,
)
from asv.core.verdicts import ContentQuality, NotCheckableReason, Verdict

Group = Literal["qual_uncited", "quant_uncited", "qual_cited", "quant_cited"]
RunStatus = Literal["queued", "running", "awaiting_login", "complete", "failed"]

# Tier 0.2 replaced the four *derived* verdicts (passed / failed /
# unresolved_source / skipped) with the pipeline's own five-value ontology,
# persisted at judgment time. `read_model` maps pre-Tier-0 run folders onto it
# so historical runs keep rendering -- see `_legacy_result_ref`.


# ---------------------------------------------------------------------------
# Claims (S3 / S4)
# ---------------------------------------------------------------------------

class CitationRef(BaseModel):
    id: Optional[str] = None
    marker: Optional[str] = None
    raw_text: Optional[str] = None
    details: Optional[CitationDetails] = None


class LocationRef(BaseModel):
    start: Optional[int] = None
    end: Optional[int] = None
    chunk_id: Optional[int] = None


class ResultRef(BaseModel):
    verdict: Verdict
    not_checkable_reason: Optional[NotCheckableReason] = None
    # DEPRECATED, derived from `verdict`. Kept so existing consumers keep
    # working for one release; `partially_substantiated` and every abstention
    # map to False, which under-counts rather than over-counts.
    passed: bool
    # None for abstentions -- a number attached to an abstention is the exact
    # failure mode Tier 0 removed.
    confidence: Optional[float] = None
    method: str
    explanation: str
    evidence: List[EvidenceSpan] = Field(default_factory=list)
    source_url: Optional[str] = None
    content_quality: Optional[ContentQuality] = None
    flags: List[str] = Field(default_factory=list)
    errors: Optional[str] = None
    sources_used: List[str] = Field(default_factory=list)
    validated_at: Optional[str] = None
    validation_metadata: Optional[Dict[str, Any]] = None
    # True when this row was reconstructed from a pre-Tier-0 run folder, whose
    # verdicts were derived after the fact and whose passes may be unsourced.
    legacy: bool = False


class BatchRef(BaseModel):
    citation_id: str
    download_successful: bool
    # Tier 0.3 -- "bytes arrived" vs "the bytes are usable as evidence".
    judgeable: bool = False
    content_quality: Optional[ContentQuality] = None
    winning_url: Optional[str] = None
    format: Optional[str] = None
    resolution_attempts: List[ResolutionAttempt] = Field(default_factory=list)
    reference_check: Optional[ReferenceCheck] = None
    notes: str
    sibling_claim_ids: List[str] = Field(default_factory=list)


class ClaimRow(BaseModel):
    claim_id: str
    text: str
    claim_type: str  # "quantitative" | "qualitative"
    group: Group
    is_original: bool
    originally_uncited: bool
    found_source: Optional[FoundDatasetSource] = None

    citation: Optional[CitationRef] = None
    location_in_text: Optional[LocationRef] = None
    result: Optional[ResultRef] = None
    batch: Optional[BatchRef] = None
    generated_script_path: Optional[str] = None


class ClaimDetail(ClaimRow):
    """ClaimRow plus the extras only the detail drawer (S4) needs."""
    raw_citation_text: Optional[str] = None
    generated_script_source: Optional[str] = None
    sibling_claims: List[ClaimRow] = Field(default_factory=list)


class ClaimsPage(BaseModel):
    claims: List[ClaimRow]
    total: int
    facets: Dict[str, Dict[str, int]] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Runs (S1 / S2)
# ---------------------------------------------------------------------------

class StepStats(BaseModel):
    elapsed_seconds: Optional[float] = None
    count: int = 0
    checkable: int = 0
    passed: int = 0          # deprecated alias for `substantiated`
    failed: int = 0          # deprecated: not_substantiated + contradicted
    avg_confidence: Optional[float] = None
    verdicts: Dict[str, int] = Field(default_factory=dict)
    not_checkable_reasons: Dict[str, int] = Field(default_factory=dict)


class VerdictBreakdown(BaseModel):
    group: Group
    substantiated: int = 0
    partially_substantiated: int = 0
    not_substantiated: int = 0
    contradicted: int = 0
    not_checkable: int = 0


class ReferenceAudit(BaseModel):
    """Tier 0.6 bibliography-audit rollup for one run."""
    total: int = 0
    verified: int = 0
    ambiguous: int = 0
    not_found_in_indexes: int = 0
    unindexed_by_design: int = 0
    unverified: int = 0
    retracted: int = 0
    concern_raised: int = 0


class ReferenceCheckRow(ReferenceCheck):
    """A bibliography-audit row, plus how many claims depend on it."""
    num_claims: int = 0


class FunnelStage(BaseModel):
    stage: str
    count: int


class CostSummary(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    input_cost: float = 0.0
    output_cost: float = 0.0
    total_cost: float = 0.0


class RunSummaryRow(BaseModel):
    run_id: str
    pdf_stem: str
    timestamp: str
    status: RunStatus
    schema_version: int = 1
    total_claims: Optional[int] = None
    substantiated: Optional[int] = None
    partially_substantiated: Optional[int] = None
    not_substantiated: Optional[int] = None
    contradicted: Optional[int] = None
    not_checkable: Optional[int] = None
    # Claims ASV could judge at all, over total claims. This is the number
    # Tier 1 acquisition work moves, and the one worth watching.
    checkable_rate: Optional[float] = None
    # Substantiated over *checkable* -- not over everything. The old
    # `pass_rate` divided by passed+failed, which put 217 unsourced
    # plausibility passes in its numerator and called the result 73%.
    substantiation_rate: Optional[float] = None
    evidence_backed_verdicts: Optional[int] = None
    reference_audit: Optional[ReferenceAudit] = None
    total_elapsed_seconds: Optional[float] = None
    cost: Optional[CostSummary] = None
    awaiting_login_domains: List[str] = Field(default_factory=list)


class RunDetail(BaseModel):
    run_id: str
    pdf_stem: str
    timestamp: str
    status: RunStatus
    schema_version: int = 1
    total_elapsed_seconds: Optional[float] = None
    cost: Optional[CostSummary] = None
    steps: Dict[str, StepStats] = Field(default_factory=dict)
    verdict_breakdown: List[VerdictBreakdown] = Field(default_factory=list)
    not_checkable_reasons: Dict[str, int] = Field(default_factory=dict)
    resolution_funnel: List[FunnelStage] = Field(default_factory=list)
    reference_audit: Optional[ReferenceAudit] = None
    awaiting_login_domains: List[str] = Field(default_factory=list)


class RunCreateRequest(BaseModel):
    pdf_path: str
    gates: Dict[str, bool] = Field(default_factory=dict)


class RunCreateResponse(BaseModel):
    run_id: str


# ---------------------------------------------------------------------------
# Sources (S6)
# ---------------------------------------------------------------------------

class SourceRow(BaseModel):
    kind: Literal["dataset", "text"]
    citation_id: str
    citation_text: Optional[str] = None
    raw_citation_text: Optional[str] = None
    citation_details: Optional[CitationDetails] = None
    resolution_attempts: List[ResolutionAttempt] = Field(default_factory=list)
    winning_url: Optional[str] = None
    format: Optional[str] = None
    filename: Optional[str] = None
    downloaded_at: Optional[str] = None
    deleted_at: Optional[str] = None
    batch_num_claims: int = 0
    batch_download_successful: bool = False
    batch_judgeable: bool = False
    content_quality: Optional[ContentQuality] = None


class RetryRequest(BaseModel):
    override_url: Optional[str] = None


class RetryResponse(BaseModel):
    citation_id: str
    download_successful: bool
    num_claims: int
    job_id: str


# ---------------------------------------------------------------------------
# Paper view (S5)
# ---------------------------------------------------------------------------

class HighlightQuad(BaseModel):
    claim_id: str
    page: int
    quads: List[List[float]]  # each inner list is [x0, y0, x1, y1], normalized 0..1


# ---------------------------------------------------------------------------
# Compare (S8)
# ---------------------------------------------------------------------------

class CompareRow(BaseModel):
    claim_id: str
    text: str
    a_verdict: Optional[Verdict] = None
    a_confidence: Optional[float] = None
    b_verdict: Optional[Verdict] = None
    b_confidence: Optional[float] = None
    changed: bool = False


class CompareResult(BaseModel):
    run_a: str
    run_b: str
    rows: List[CompareRow]


# ---------------------------------------------------------------------------
# Config / health
# ---------------------------------------------------------------------------

class ConfigStatus(BaseModel):
    env_keys: Dict[str, bool]
    thresholds: Dict[str, Any]
