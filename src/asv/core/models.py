"""Pydantic models for structured data"""

from pydantic import BaseModel, Field, computed_field, model_validator
from typing import Optional, List, Dict, Any, Literal
from datetime import datetime

from asv.core.verdicts import (
    ContentQuality,
    EVIDENCED_VERDICTS,
    NotCheckableReason,
    ReferenceStatus,
    RetractionStatus,
    Verdict,
)

#: Bumped when the shape of ``validation_results/*.json`` changes in a way the
#: API read model has to know about. v2 = Tier 0: every result carries a
#: ``verdict``, an optional ``not_checkable_reason``, and ``evidence`` spans.
#:
#: Deviation from TIER0_PLAN.md §9: rather than wrapping each results file in an
#: object to carry ``"_schema": 2`` (which would break the list shape every
#: existing analysis snippet assumes), the version is written once per run to
#: ``validation_results/_schema.json`` and each *entry* is additionally
#: self-describing — the API treats an entry without a ``verdict`` key as legacy.
#: That also handles the mixed-shape file ``revalidate_citation`` can produce
#: when a retry writes into a pre-Tier-0 run folder.
RESULT_SCHEMA_VERSION = 2


class CitationDetails(BaseModel):
    """Details about a citation"""
    title: Optional[str] = None
    authors: Optional[List[str]] = None
    year: Optional[int] = None
    url: Optional[str] = None
    doi: Optional[str] = None
    raw_text: str  # Original citation text


class LocationInText(BaseModel):
    """Character span of a claim within the full extracted document text.

    ``start``/``end`` are absolute character offsets into the text passed to the
    claim extractor (the full PDF text), suitable for highlighting the claim in
    the source. They are ``None`` when the claim could not be located in the
    source text (e.g. the LLM paraphrased it beyond a whitespace-tolerant match).
    """
    start: Optional[int] = None
    end: Optional[int] = None
    chunk_id: Optional[int] = None


class FoundDatasetSource(BaseModel):
    """Dataset source found by sourcefinder for originally uncited claims"""
    source_url: str
    source_type: str  # "data.gov", "kaggle", "arxiv", etc.
    relevance_score: float
    found_by_claim_id: str  # Original claim that triggered the search
    reused_count: int = 0  # How many other claims reused this source
    search_query: Optional[str] = None
    found_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class ClaimObject(BaseModel):
    """Claim object from Step 1: Claim Identification + Citation Mapping"""
    claim_id: str
    text: str
    claim_type: str = Field(..., description="quantitative or qualitative")
    citation_found: bool
    citation_id: Optional[str] = None  # Key to citations dict for batch processing
    citation_text: Optional[str] = None  # e.g., "[1]" or "(Smith, 2020)"
    citation_details: Optional[CitationDetails] = None
    is_original: bool = Field(default=False, description="True if claim is original contribution from paper (no external citation or references paper's own figures/tables)")
    originally_uncited: bool = Field(default=False, description="True if citation was found by sourcefinder (not in original paper)")
    found_source: Optional[FoundDatasetSource] = None  # Populated if originally_uncited=True
    location_in_text: Optional[LocationInText] = None

    @model_validator(mode='after')
    def validate_original_and_citation(self) -> 'ClaimObject':
        """Ensure claims cannot be both original and have external citations"""
        if self.is_original and self.citation_found:
            raise ValueError(
                f"Claim {self.claim_id} cannot be both original (is_original=True) "
                f"and have an external citation (citation_found=True). "
                f"Original claims are from the paper's own work and should not cite external sources."
            )
        return self


class EvidenceSpan(BaseModel):
    """One quoted passage backing a verdict — Tier 0.5.

    The whole point is that a human can check the finding in ten seconds:
    ``quote`` is verbatim text from the source, ``source_url`` resolves to the
    thing that was actually fetched, and ``verified_verbatim`` records whether
    ASV confirmed the quote really appears there (LLMs fabricate quotes; see
    VALUE_PROPOSITION.md §2.4(c) for this system doing exactly that once).
    """
    quote: str
    role: Literal["supporting", "contradicting", "nearest_relevant"] = "supporting"
    source_url: str
    retrieval_score: Optional[float] = None
    char_start: Optional[int] = None
    char_end: Optional[int] = None
    locator: Optional[str] = None  # best-effort "p. 4" / section heading
    verified_verbatim: bool = False


class ReferenceCheck(BaseModel):
    """Does the cited reference exist in the scholarly record? — Tier 0.6.

    Orthogonal to the claim verdict: a reference that cannot be found says
    nothing about whether the claim is true, and a retracted source can still
    contain the sentence being cited. Both surface as their own object plus
    ``ValidationResult.flags`` rather than as verdicts.

    ``indexes_queried`` vs ``indexes_responded`` is the whole of the
    "an API outage must never read as an accusation" rule: a
    ``NOT_FOUND_IN_INDEXES`` status requires at least two indexes to have
    actually responded.
    """
    citation_id: str
    raw_citation_text: str
    parsed: Dict[str, Any] = Field(default_factory=dict)
    status: ReferenceStatus
    matched_doi: Optional[str] = None
    matched_title: Optional[str] = None
    matched_url: Optional[str] = None
    match_score: Optional[float] = None
    near_miss: Optional[Dict[str, Any]] = None
    indexes_queried: List[str] = Field(default_factory=list)
    indexes_responded: List[str] = Field(default_factory=list)
    retraction_status: RetractionStatus = RetractionStatus.UNKNOWN
    retraction_notice_url: Optional[str] = None
    explanation: str = ""
    checked_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class ValidationResult(BaseModel):
    """Result of validation for any claim.

    Tier 0.2/0.5 contract: ``verdict`` is the answer; ``passed`` is a derived,
    deprecated view of it. The model validator below makes it *impossible* to
    construct a judgment without evidence, or an abstention with a confidence
    score — the two shapes VALUE_PROPOSITION.md §0 identifies as the system
    manufacturing unearned confidence.
    """
    claim_id: str
    claim_type: str  # Store original claim type (quantitative/qualitative)
    originally_uncited: bool  # Track if claim was originally without citation

    # --- the verdict (Tier 0.2) -------------------------------------------
    verdict: Verdict
    not_checkable_reason: Optional[NotCheckableReason] = None

    validated: bool  # True when a judgment was actually attempted against a source
    validation_method: str  # "rag_search" | "python_script" | "not_checkable"
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    explanation: str

    # --- the evidence (Tier 0.5) ------------------------------------------
    evidence: List[EvidenceSpan] = Field(default_factory=list)
    source_url: Optional[str] = None
    source_fetched_at: Optional[str] = None
    content_quality: Optional[ContentQuality] = None

    #: Orthogonal signals that must never become verdicts —
    #: "cited_source_retracted", "cited_source_concern_raised",
    #: "reference_unindexed", "claimed_original".
    flags: List[str] = Field(default_factory=list)

    #: DEPRECATED. Historically held three different things: quotes, a local
    #: dataset path, and fact-check URLs. Going forward: URLs only. Quotes live
    #: in ``evidence``.
    sources_used: List[str] = Field(default_factory=list)

    errors: Optional[str] = None
    validation_metadata: Optional[Dict[str, Any]] = None
    validated_at: str = Field(default_factory=lambda: datetime.now().isoformat())

    @computed_field  # type: ignore[prop-decorator]
    @property
    def passed(self) -> bool:
        """DEPRECATED — derived from ``verdict``. Read ``verdict`` instead.

        Deliberately conservative: ``partially_substantiated`` and every
        abstention map to ``False``, so a legacy consumer filtering
        ``passed == true`` under-counts rather than over-counts. For a tool
        whose named failure mode is unearned confidence, under-counting is the
        only acceptable direction to be wrong in.

        Kept (rather than deleted) for one release so the API read model, the
        run summary, the compare view and eight historical run folders keep
        working. Being computed rather than stored means it cannot disagree
        with ``verdict`` — which is the property that actually mattered.
        """
        return self.verdict == Verdict.SUBSTANTIATED

    @model_validator(mode='after')
    def _enforce_verdict_invariants(self) -> 'ValidationResult':
        """Tier 0.5, enforced at construction so the bad state is unrepresentable.

        A convention prevents a bad verdict until the next contributor; a
        constructor invariant fails loudly in tests, before a user ever sees it.
        """
        if self.verdict in EVIDENCED_VERDICTS:
            if not self.evidence:
                raise ValueError(
                    f"{self.claim_id}: verdict={self.verdict.value} requires at least one "
                    f"EvidenceSpan (Tier 0.5). Use NOT_CHECKABLE with a reason code instead."
                )
            if not any(e.verified_verbatim for e in self.evidence):
                raise ValueError(
                    f"{self.claim_id}: verdict={self.verdict.value} requires at least one "
                    f"verbatim-verified EvidenceSpan (Tier 0.5)."
                )
            if not self.source_url:
                raise ValueError(
                    f"{self.claim_id}: verdict={self.verdict.value} requires a resolvable "
                    f"source_url (Tier 0.5)."
                )

        if self.verdict == Verdict.NOT_CHECKABLE:
            if self.not_checkable_reason is None:
                raise ValueError(
                    f"{self.claim_id}: verdict=not_checkable requires a reason code."
                )
            if self.confidence is not None:
                raise ValueError(
                    f"{self.claim_id}: verdict=not_checkable must not carry a confidence "
                    f"score — an abstention with a number attached is the exact failure "
                    f"mode Tier 0 removes."
                )
        elif self.not_checkable_reason is not None:
            raise ValueError(
                f"{self.claim_id}: not_checkable_reason set on verdict="
                f"{self.verdict.value}."
            )

        return self


class ResolutionAttempt(BaseModel):
    """One URL try when resolving a citation to a downloadable source."""
    url: str
    source: str  # "direct", "open_access", "found_dataset", "institutional_cookies", "browser"
    downloaded: bool
    #: Tier 0.3 — recorded for *every* attempt, not just the winner, so the
    #: manifests become the calibration corpus for the content classifier
    #: instead of a dead-end log.
    content_quality: Optional[ContentQuality] = None
    error: Optional[str] = None


class ValidationBatch(BaseModel):
    """Results for a batch of claims sharing same citation"""
    citation_id: str
    citation_text: Optional[str] = None
    download_successful: bool
    #: Tier 0.3 — ``download_successful`` answers "did bytes arrive"; this
    #: answers "are those bytes evidence". Separating them is the whole item.
    judgeable: bool = False
    content_quality: Optional[ContentQuality] = None
    source_path: Optional[str] = None
    source_url: Optional[str] = None
    resolution_attempts: List[ResolutionAttempt] = Field(default_factory=list)
    reference_check: Optional[ReferenceCheck] = None
    claim_results: List[ValidationResult]
    batch_notes: str


class SourceManifestEntry(BaseModel):
    """One record in the per-run datasets/ or text_sources/ manifest.

    Survives batch cleanup: the local file at ``filename`` is deleted after the
    batch completes, but this entry preserves everything needed to trace the
    source (title, URL cascade, format, timestamps, batch outcome).
    """
    citation_id: str
    citation_text: Optional[str] = None
    raw_citation_text: Optional[str] = None
    citation_details: Optional[CitationDetails] = None
    resolution_attempts: List[ResolutionAttempt] = Field(default_factory=list)
    winning_url: Optional[str] = None
    format: Optional[str] = None
    content_quality: Optional[ContentQuality] = None
    content_signals: Optional[Dict[str, Any]] = None
    filename: Optional[str] = None
    downloaded_at: Optional[str] = None
    deleted_at: Optional[str] = None
    batch_num_claims: int = 0
    batch_download_successful: bool = False
    batch_judgeable: bool = False
    found_source: Optional[FoundDatasetSource] = None


# ---------------------------------------------------------------------------
# Construction helper
# ---------------------------------------------------------------------------

def not_checkable(
    claim,
    reason: NotCheckableReason,
    explanation: str,
    *,
    method: str = "not_checkable",
    errors: Optional[str] = None,
    flags: Optional[List[str]] = None,
    source_url: Optional[str] = None,
    content_quality: Optional[ContentQuality] = None,
    validation_metadata: Optional[Dict[str, Any]] = None,
) -> ValidationResult:
    """Build an abstention for ``claim`` — the single most common result shape.

    Centralised so no call site has to remember that abstentions carry no
    confidence and that ``validated`` is False.
    """
    extra_flags = list(flags or [])
    if getattr(claim, "is_original", False) and "claimed_original" not in extra_flags:
        extra_flags.append("claimed_original")

    return ValidationResult(
        claim_id=claim.claim_id,
        claim_type=claim.claim_type,
        originally_uncited=getattr(claim, "originally_uncited", False),
        verdict=Verdict.NOT_CHECKABLE,
        not_checkable_reason=reason,
        validated=False,
        validation_method=method,
        confidence=None,
        explanation=explanation,
        evidence=[],
        source_url=source_url,
        content_quality=content_quality,
        flags=extra_flags,
        sources_used=[],
        errors=errors,
        validation_metadata=validation_metadata,
    )
