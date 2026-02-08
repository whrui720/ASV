"""Dataset Finder - Search for data repositories for quantitative claims"""

import json
import logging
from typing import List, Optional, Dict, Any
from models import FoundDatasetSource
from hybrid_citation_scraper.llm_client import LLMClient

logger = logging.getLogger(__name__)


class DatasetFinder:
    """Search for data repositories for quantitative claims with LLM-based reuse logic"""
    
    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client
        self.found_datasets: List[FoundDatasetSource] = []
    
    def find_dataset(
        self, 
        claim_text: str, 
        claim_id: str,
        existing_datasets: Optional[List[FoundDatasetSource]] = None
    ) -> Optional[FoundDatasetSource]:
        """
        Find dataset for quantitative claim.
        First checks if existing datasets are applicable (LLM decision).
        If not, searches new repositories.
        """
        if existing_datasets is None:
            existing_datasets = self.found_datasets
        
        # Step 1: Ask LLM if any existing dataset is suitable
        if existing_datasets:
            logger.info(f"Checking {len(existing_datasets)} existing datasets for reuse...")
            suitable_dataset = self._check_existing_datasets(claim_text, existing_datasets)
            if suitable_dataset:
                suitable_dataset.reused_count += 1
                logger.info(f"✓ Reusing dataset: {suitable_dataset.source_url}")
                return suitable_dataset
        
        # Step 2: Search new datasets
        logger.info("Searching for new datasets...")
        candidates = self._search_repositories(claim_text)
        if not candidates:
            logger.warning("No dataset candidates found")
            return None
        
        # Step 3: LLM ranks candidates
        best_match = self._rank_candidates(claim_text, candidates)
        if not best_match:
            return None
        
        # Step 4: Create FoundDatasetSource
        found_source = FoundDatasetSource(
            source_url=best_match['url'],
            source_type=best_match['source'],
            relevance_score=best_match['score'],
            found_by_claim_id=claim_id,
            search_query=best_match.get('query', claim_text)
        )
        
        self.found_datasets.append(found_source)
        logger.info(f"✓ Found new dataset: {found_source.source_url}")
        
        return found_source
    
    def _check_existing_datasets(
        self, 
        claim_text: str, 
        datasets: List[FoundDatasetSource]
    ) -> Optional[FoundDatasetSource]:
        """Use LLM to decide if existing dataset is applicable"""
        
        datasets_desc = "\n".join([
            f"{i+1}. [{d.source_type}] {d.source_url} (relevance: {d.relevance_score:.2f}, used by {d.reused_count} claims)"
            for i, d in enumerate(datasets)
        ])
        
        prompt = f"""You are evaluating if any existing dataset can validate a new claim.

Claim to validate: {claim_text}

Available datasets:
{datasets_desc}

Can any of these datasets be used to validate this claim? Consider:
- Does the dataset contain relevant variables/metrics?
- Is the time period appropriate?
- Is the geographic scope appropriate?

Return JSON: {{"can_reuse": true/false, "dataset_index": 1-{len(datasets)} or null, "confidence": 0.0-1.0, "reasoning": "explanation"}}
"""
        
        try:
            response = self.llm_client.client.chat.completions.create(
                model=self.llm_client.model,
                messages=[
                    {"role": "system", "content": "You are a data analyst evaluating dataset applicability."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                response_format={"type": "json_object"}
            )
            
            content = response.choices[0].message.content or "{}"
            result = json.loads(content)
            
            if result.get('can_reuse') and result.get('confidence', 0) > 0.75:
                idx = result.get('dataset_index')
                if idx and 1 <= idx <= len(datasets):
                    return datasets[idx - 1]
            
            return None
            
        except Exception as e:
            logger.error(f"LLM check failed: {e}")
            return None
    
    def _search_repositories(self, claim_text: str) -> List[Dict[str, Any]]:
        """Search data repositories (data.gov, Kaggle, etc.)"""
        candidates = []
        
        # Simple placeholder - in production would query actual APIs
        # For now, return mock results for testing
        logger.warning("Using mock dataset search - implement actual API integration")
        
        # Mock result
        candidates.append({
            'url': f'https://data.gov/dataset/mock_{hash(claim_text) % 1000}',
            'title': f'Mock dataset for: {claim_text[:50]}...',
            'source': 'data.gov',
            'description': 'Mock dataset description',
            'score': 0.8
        })
        
        return candidates
    
    def _rank_candidates(self, claim_text: str, candidates: List[Dict]) -> Optional[Dict]:
        """Use LLM to rank candidate datasets"""
        if not candidates:
            return None
        
        # For now, return highest scoring candidate
        # In production, would use LLM to re-rank
        return max(candidates, key=lambda x: x.get('score', 0))
