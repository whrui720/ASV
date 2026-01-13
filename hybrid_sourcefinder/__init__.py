"""
Hybrid Source Finder - Step 2: Claim Type Treatment

Processes claims from Step 1 (hybrid_citation_scraper) and performs:
- Source finding and downloading for quantitative claims
- Dataset search for claims without citations
- Text downloading for qualitative claims
- Truth table queries for subjective claims

Main entry point: ClaimTreatmentAgent
"""

from .claim_treatment_agent import ClaimTreatmentAgent
from .source_finder import SourceFinder
from .dataset_searcher import DatasetSearcher
from .text_downloader import TextDownloader
from .truth_table_checker import TruthTableChecker

__all__ = [
    'ClaimTreatmentAgent',
    'SourceFinder',
    'DatasetSearcher',
    'TextDownloader',
    'TruthTableChecker'
]
