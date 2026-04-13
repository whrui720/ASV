"""Dataset Finder - Search for data repositories for quantitative claims"""

import logging
import requests
from typing import List, Optional, Dict, Any
from models import FoundDatasetSource
from hybrid_citation_scraper.llm_client import LLMClient
from .config import DATA_GOV_API, KAGGLE_USERNAME, KAGGLE_KEY, DEFAULT_TOP_K, DOWNLOAD_TIMEOUT

logger = logging.getLogger(__name__)


class DatasetFinder:
    """Search for data repositories for quantitative claims with LLM-based reuse logic"""

    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client
        self.found_datasets: List[FoundDatasetSource] = []
        self.browser_searcher = None  # injected by orchestrator after startup login
    
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
            result = self.llm_client.call_llm(
                prompt,
                response_format="json",
                task_name="dataset_reuse_decision",
                system_message="You are a data analyst evaluating dataset applicability.",
            )
            
            if result.get('can_reuse') and result.get('confidence', 0) > 0.75:
                idx = result.get('dataset_index')
                if idx and 1 <= idx <= len(datasets):
                    return datasets[idx - 1]
            
            return None
            
        except Exception as e:
            logger.error(f"LLM check failed: {e}")
            return None
    
    def _search_repositories(self, claim_text: str) -> List[Dict[str, Any]]:
        """Search data repositories (data.gov, Kaggle, then browser fallbacks) for datasets."""
        candidates = []
        query = claim_text[:100]

        candidates.extend(self._search_data_gov(query))
        if KAGGLE_USERNAME and KAGGLE_KEY:
            candidates.extend(self._search_kaggle(query))
        else:
            logger.debug("Kaggle credentials not set; skipping Kaggle search")

        # Browser fallback: Zenodo, Figshare, HuggingFace
        if not candidates and self.browser_searcher is not None:
            logger.info("APIs returned no results — falling back to browser search (Zenodo/Figshare/HuggingFace)")
            candidates.extend(self._search_browser(query))

        if not candidates:
            logger.warning(f"No dataset candidates found for query: {query[:60]}...")
        return candidates

    def _search_browser(self, query: str) -> List[Dict[str, Any]]:
        """Search Zenodo, Figshare, and HuggingFace Datasets via browser."""
        candidates = []
        sources = [
            ("zenodo", self.browser_searcher.search_zenodo),
            ("figshare", self.browser_searcher.search_figshare),
            ("huggingface", self.browser_searcher.search_huggingface_datasets),
        ]
        for source_name, search_fn in sources:
            try:
                urls = search_fn(query, top_k=3)
                for url in urls:
                    candidates.append({
                        "url": url,
                        "title": f"{source_name} dataset",
                        "source": source_name,
                        "description": "",
                        "score": 0.65,
                        "query": query,
                    })
                if urls:
                    logger.info(f"  Browser ({source_name}): {len(urls)} candidates")
            except Exception as e:
                logger.warning(f"  Browser search failed ({source_name}): {e}")
        return candidates

    def _search_data_gov(self, query: str) -> List[Dict[str, Any]]:
        """Search data.gov CKAN API for relevant datasets."""
        candidates = []
        try:
            response = requests.get(
                DATA_GOV_API,
                params={"q": query, "rows": DEFAULT_TOP_K},
                timeout=DOWNLOAD_TIMEOUT,
            )
            response.raise_for_status()
            data = response.json()
            results = data.get("result", {}).get("results", [])
            for item in results:
                # Prefer the first CSV/JSON resource; fall back to the dataset page
                resource_url = None
                for res in item.get("resources", []):
                    fmt = (res.get("format") or "").lower()
                    if fmt in ("csv", "json", "xlsx", "xls"):
                        resource_url = res.get("url")
                        break
                if not resource_url:
                    resource_url = f"https://catalog.data.gov/dataset/{item.get('name', '')}"

                candidates.append({
                    "url": resource_url,
                    "title": item.get("title", ""),
                    "source": "data.gov",
                    "description": (item.get("notes") or "")[:200],
                    "score": 0.7,
                    "query": query,
                })
            logger.info(f"data.gov returned {len(candidates)} candidates")
        except Exception as e:
            logger.warning(f"data.gov search failed: {e}")
        return candidates

    def _search_kaggle(self, query: str) -> List[Dict[str, Any]]:
        """Search Kaggle datasets using the kaggle package."""
        candidates = []
        try:
            import kaggle  # noqa: F401 — triggers auth from env vars
            from kaggle.api.kaggle_api_extended import KaggleApiExtended
            api = KaggleApiExtended()
            api.authenticate()
            results = api.dataset_list(search=query, page_size=DEFAULT_TOP_K)
            for item in results:
                ref = getattr(item, "ref", None)
                if ref:
                    candidates.append({
                        "url": f"https://www.kaggle.com/datasets/{ref}",
                        "title": getattr(item, "title", ref),
                        "source": "kaggle",
                        "description": getattr(item, "subtitle", ""),
                        "score": 0.7,
                        "query": query,
                    })
            logger.info(f"Kaggle returned {len(candidates)} candidates")
        except Exception as e:
            logger.warning(f"Kaggle search failed: {e}")
        return candidates
    
    def _rank_candidates(self, claim_text: str, candidates: List[Dict]) -> Optional[Dict]:
        """Use LLM to rank candidate datasets"""
        if not candidates:
            return None
        
        # For now, return highest scoring candidate
        # In production, would use LLM to re-rank
        return max(candidates, key=lambda x: x.get('score', 0))
