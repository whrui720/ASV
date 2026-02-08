"""Pydantic models for structured data"""

from pydantic import BaseModel, Field, model_validator
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


class ValidationResult(BaseModel):
    """Result of validation for any claim"""
    claim_id: str
    claim_type: str  # Store original claim type (quantitative/qualitative)
    originally_uncited: bool  # Track if claim was originally without citation
    validated: bool
    validation_method: str  # "truth_table", "llm_check", "python_script", "rag_search", "combined"
    confidence: float = Field(..., ge=0.0, le=1.0)
    passed: bool  # True if claim is verified/valid
    explanation: str
    sources_used: List[str] = Field(default_factory=list)
    errors: Optional[str] = None
    validation_metadata: Optional[Dict[str, Any]] = None
    validated_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class ValidationBatch(BaseModel):
    """Results for a batch of claims sharing same citation"""
    citation_id: str
    citation_text: Optional[str] = None
    download_successful: bool
    source_path: Optional[str] = None
    claim_results: List[ValidationResult]
    batch_notes: str
