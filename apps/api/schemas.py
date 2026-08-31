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

from asv.core.models import CitationDetails, FoundDatasetSource, ResolutionAttempt

Verdict = Literal["passed", "failed", "unresolved_source", "skipped"]
Group = Literal["qual_uncited", "quant_uncited", "qual_cited", "quant_cited"]
RunStatus = Literal["queued", "running", "awaiting_login", "complete", "failed"]


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
    passed: bool
    confidence: float
    method: str
    explanation: str
    errors: Optional[str] = None
    sources_used: List[str] = Field(default_factory=list)
    validated_at: Optional[str] = None
    validation_metadata: Optional[Dict[str, Any]] = None


class BatchRef(BaseModel):
    citation_id: str
    download_successful: bool
    winning_url: Optional[str] = None
    format: Optional[str] = None
    resolution_attempts: List[ResolutionAttempt] = Field(default_factory=list)
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
    passed: int = 0
    failed: int = 0
    avg_confidence: Optional[float] = None


class VerdictBreakdown(BaseModel):
    group: Group
    passed: int = 0
    failed: int = 0
    unresolved_source: int = 0
    skipped: int = 0


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
    total_claims: Optional[int] = None
    passed: Optional[int] = None
    failed: Optional[int] = None
    unresolved_source: Optional[int] = None
    pass_rate: Optional[float] = None
    unresolved_source_rate: Optional[float] = None
    total_elapsed_seconds: Optional[float] = None
    cost: Optional[CostSummary] = None
    awaiting_login_domains: List[str] = Field(default_factory=list)


class RunDetail(BaseModel):
    run_id: str
    pdf_stem: str
    timestamp: str
    status: RunStatus
    total_elapsed_seconds: Optional[float] = None
    cost: Optional[CostSummary] = None
    steps: Dict[str, StepStats] = Field(default_factory=dict)
    verdict_breakdown: List[VerdictBreakdown] = Field(default_factory=list)
    resolution_funnel: List[FunnelStage] = Field(default_factory=list)
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
