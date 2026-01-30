"""Pydantic models for structured data"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime


class CitationDetails(BaseModel):
    """Details about a citation"""
    title: Optional[str] = None
    authors: Optional[List[str]] = None
    year: Optional[int] = None
    url: Optional[str] = None
    doi: Optional[str] = None
    raw_text: str  # Original citation text


class LocationInText(BaseModel):
    """Location of claim in source text"""
    start: int
    end: int
    chunk_id: Optional[int] = None


class ClaimObject(BaseModel):
    """Claim object from Step 1: Claim Identification + Citation Mapping"""
    claim_id: str
    text: str
    claim_type: str = Field(..., description="quantitative or qualitative")
    citation_found: bool
    citation_id: Optional[str] = None  # Key to citations dict for batch processing
    citation_text: Optional[str] = None  # e.g., "[1]" or "(Smith, 2020)"
    citation_details: Optional[CitationDetails] = None
    classification: List[str] = Field(default_factory=list, description="objective, subjective, etc.")
    location_in_text: Optional[LocationInText] = None
    

class CitationSource(BaseModel):
    """Source information for a claim"""
    downloaded: bool = False
    data_format: Optional[str] = None  # csv, json, pdf, etc.
    platform: Optional[str] = None  # pandas, R, etc.
    source_url: Optional[str] = None
    local_path: Optional[str] = None


class ClaimObjectAfterTreatment(BaseModel):
    """Claim object from Step 2: Claim Type Treatment"""
    claim_id: str
    text: str
    claim_type: str
    citation_mapped: bool
    citation_source: Optional[CitationSource] = None
    treatment_notes: str


class ValidationResult(BaseModel):
    """Validation result details"""
    is_factual: bool
    is_appropriate: bool
    explanation: str


class ValidationMetadata(BaseModel):
    """Metadata about validation process"""
    checked_by: str = "automated_agent"
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    model_used: Optional[str] = None


class JudgementObject(BaseModel):
    """Judgement object from Step 3: Claim Validation"""
    claim_id: str
    validation_type: str  # quantitative or qualitative
    validation_code: Optional[str] = None  # Python code used for validation
    result: ValidationResult
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    validation_metadata: ValidationMetadata


class ReportClaim(BaseModel):
    """Claim summary for report"""
    claim_id: str
    text: str
    judgement: ValidationResult
    citation: Optional[Dict[str, str]] = None


class ReportSummary(BaseModel):
    """Summary statistics for report"""
    total_claims: int
    validated: int
    issues_found: int
    quantitative_claims: int = 0
    qualitative_claims: int = 0


class ReportObject(BaseModel):
    """Report object from Step 4: Display"""
    claims: List[ReportClaim]
    summary: ReportSummary
    source_document: str
    generated_at: str = Field(default_factory=lambda: datetime.now().isoformat())
