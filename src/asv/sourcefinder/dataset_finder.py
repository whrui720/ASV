"""Dataset Finder - Search for data repositories for quantitative claims"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any, TYPE_CHECKING

from asv.core.models import FoundDatasetSource
from asv.extraction.llm_client import LLMClient
from asv.core.run_paths import RunPaths
from .config import (
    MIN_RELEVANCE_SCORE,
    DATACITE_SEARCH_API,
    DATA_GOV_API,
    ENABLE_DATA_GOV,
    DEFAULT_TOP_K,
    DOWNLOAD_TIMEOUT,
    FIGSHARE_SEARCH_API,
    HUGGINGFACE_DATASETS_API,
    KAGGLE_KEY,
    KAGGLE_USERNAME,
    ZENODO_API,
)
from .polite_http import PoliteSession, api_user_agent

if TYPE_CHECKING:
    from .browser_searcher import BrowserSearcher

logger = logging.getLogger(__name__)


class DatasetFinder:
    """Search for data repositories for quantitative claims with LLM-based reuse logic"""

    def __init__(self, llm_client: LLMClient, run_paths: Optional[RunPaths] = None):
        self.llm_client = llm_client
        self.found_datasets: List[FoundDatasetSource] = []
        self.browser_searcher: Optional["BrowserSearcher"] = None  # injected by orchestrator after startup login
        self.run_paths = run_paths
        # Registries want a contactable research agent, not a browser string:
        # zenodo.org/api returns 403 to the Chrome UA and 200 to this one.
        self.session = PoliteSession(
            api_user_agent(), default_headers={"Accept": "application/json"}
        )
        #: LLM-built search queries, cached per claim so a re-search is free.
        self._query_cache: Dict[str, str] = {}

    def save_discovery_records(self) -> Optional[Path]:
        """Flush in-memory dataset discoveries to the run's sourcefinder folder."""
        if self.run_paths is None:
            return None
        path = self.run_paths.found_datasets_json()
        payload = {
            "run_timestamp": datetime.now().isoformat(),
            "pdf_stem": self.run_paths.pdf_stem,
            "count": len(self.found_datasets),
            "datasets": [d.model_dump() for d in self.found_datasets],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        return path
    
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
    
    def _build_search_query(self, claim_text: str) -> str:
        """Turn a claim sentence into search terms a data registry can match.

        The old code sent ``claim_text[:100]`` — a truncated English sentence —
        to data.gov and Kaggle. For a virology paper that cannot work: the
        sentence carries hedges, citations and clause structure, and the
        registries index dataset titles and keywords. Asking the LLM for the
        measured entities is the same one cheap call, spent better (F10).
        """
        key = claim_text[:300]
        if key in self._query_cache:
            return self._query_cache[key]

        fallback = claim_text[:100]
        prompt = (
            "Extract the search terms that would find a DATASET able to check "
            "this claim. Return the measured entities, populations, geographies "
            "and time periods as keywords — not a sentence, no hedging words, no "
            "citation markers.\n\n"
            f"Claim: {claim_text[:600]}\n\n"
            'Return JSON: {"query": "6-10 keywords", "measures": ["..."]}. '
            'If no dataset could possibly exist for this claim, return '
            '{"query": null, "measures": []}.'
        )
        try:
            result = self.llm_client.call_llm(
                prompt,
                response_format="json",
                task_name="dataset_query_building",
                system_message="You build search queries for scientific data repositories.",
            )
            query = (result or {}).get("query") or fallback
        except Exception as e:
            logger.debug(f"  Query building failed ({e}); using raw claim text")
            query = fallback

        query = str(query)[:200]
        self._query_cache[key] = query
        return query

    def _search_repositories(self, claim_text: str) -> List[Dict[str, Any]]:
        """Search every dataset registry that indexes scientific data.

        All six are queried and pooled rather than short-circuited on the first
        hit, for the same reason the paper resolver does: data.gov and Kaggle do
        not overlap a biomedical corpus at all, so a cascade that stops when
        they answer stops with the wrong answer.
        """
        query = self._build_search_query(claim_text)
        logger.info(f"  Dataset query: {query!r}")

        candidates: List[Dict[str, Any]] = []
        searches = [
            ("zenodo", self._search_zenodo),
            ("figshare", self._search_figshare),
            ("datacite", self._search_datacite),
            ("huggingface", self._search_huggingface),
        ]
        if ENABLE_DATA_GOV:
            searches.insert(0, ("data.gov", self._search_data_gov))
        if KAGGLE_USERNAME and KAGGLE_KEY:
            searches.insert(1, ("kaggle", self._search_kaggle))
        else:
            logger.debug("Kaggle credentials not set; skipping Kaggle search")

        for name, search_fn in searches:
            try:
                found = search_fn(query)
                candidates.extend(found)
                if found:
                    logger.info(f"  {name}: {len(found)} candidate(s)")
            except Exception as e:
                logger.warning(f"  {name} search failed: {e}")

        if not candidates:
            logger.warning(f"No dataset candidates found for query: {query[:60]}...")
        return candidates

    def _search_zenodo(self, query: str) -> List[Dict[str, Any]]:
        """Zenodo REST. Replaces a browser scrape that returned nothing, ever."""
        resp = self.session.get(
            ZENODO_API,
            params={"q": query, "size": DEFAULT_TOP_K, "type": "dataset"},
            timeout=DOWNLOAD_TIMEOUT,
        )
        if resp.status_code >= 400:
            return []
        out = []
        for hit in ((resp.json().get("hits") or {}).get("hits") or [])[:DEFAULT_TOP_K]:
            meta = hit.get("metadata") or {}
            # Prefer a direct file link — the record page is HTML the dataset
            # downloader would correctly refuse.
            url = None
            for f in hit.get("files") or []:
                key = str(f.get("key") or "").lower()
                if key.endswith((".csv", ".xlsx", ".xls", ".json", ".tsv")):
                    url = ((f.get("links") or {}).get("self"))
                    break
            if not url:
                continue
            out.append({
                "url": url,
                "title": meta.get("title") or hit.get("title") or "",
                "source": "zenodo",
                "description": (meta.get("description") or "")[:300],
                "score": 0.7,
                "query": query,
            })
        return out

    def _search_figshare(self, query: str) -> List[Dict[str, Any]]:
        """Figshare REST. POST with a JSON body — the GET form 404s."""
        resp = self.session.session.post(
            FIGSHARE_SEARCH_API,
            json={"search_for": query, "limit": DEFAULT_TOP_K, "item_type": 3},
            timeout=DOWNLOAD_TIMEOUT,
        )
        if resp.status_code >= 400:
            return []
        out = []
        for item in (resp.json() or [])[:DEFAULT_TOP_K]:
            url = item.get("url_public_api") or item.get("url")
            if not url:
                continue
            out.append({
                "url": url,
                "title": item.get("title") or "",
                "source": "figshare",
                "description": (item.get("description") or "")[:300],
                "score": 0.65,
                "query": query,
            })
        return out

    def _search_datacite(self, query: str) -> List[Dict[str, Any]]:
        """DataCite is to datasets what Crossref is to articles — the registry
        that actually indexes the repositories scientific data lives in. This is
        the piece DatasetFinder was missing entirely."""
        resp = self.session.get(
            DATACITE_SEARCH_API,
            params={
                "query": query, "page[size]": DEFAULT_TOP_K,
                "resource-type-id": "dataset",
            },
            timeout=DOWNLOAD_TIMEOUT,
        )
        if resp.status_code >= 400:
            return []
        out = []
        for node in (resp.json().get("data") or [])[:DEFAULT_TOP_K]:
            attrs = node.get("attributes") or {}
            url = attrs.get("url") or (
                f"https://doi.org/{attrs['doi']}" if attrs.get("doi") else None
            )
            if not url:
                continue
            titles = attrs.get("titles") or []
            title = titles[0].get("title") if titles and isinstance(titles[0], dict) else ""
            out.append({
                "url": url,
                "title": title or "",
                "source": "datacite",
                "description": str(attrs.get("publisher") or "")[:300],
                "score": 0.65,
                "query": query,
            })
        return out

    def _search_huggingface(self, query: str) -> List[Dict[str, Any]]:
        """HuggingFace Datasets. Keyless JSON; the browser scrape never worked."""
        resp = self.session.get(
            HUGGINGFACE_DATASETS_API,
            params={"search": query, "limit": DEFAULT_TOP_K},
            timeout=DOWNLOAD_TIMEOUT,
        )
        if resp.status_code >= 400:
            return []
        out = []
        for item in (resp.json() or [])[:DEFAULT_TOP_K]:
            ref = item.get("id")
            if not ref:
                continue
            out.append({
                "url": f"https://huggingface.co/api/datasets/{ref}/parquet",
                "title": ref,
                "source": "huggingface",
                "description": ", ".join(item.get("tags") or [])[:300],
                "score": 0.6,
                "query": query,
            })
        return out

    def _search_data_gov(self, query: str) -> List[Dict[str, Any]]:
        """Search data.gov CKAN API for relevant datasets."""
        candidates = []
        try:
            response = self.session.get(
                DATA_GOV_API,
    ENABLE_DATA_GOV,
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
            from kaggle.api.kaggle_api_extended import KaggleApi
            api = KaggleApi()
            api.authenticate()
            results = api.dataset_list(search=query)
            for item in results[:DEFAULT_TOP_K]:
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
        """Ask the LLM which candidate could actually settle this claim.

        This used to be ``max(candidates, key=score)`` over hardcoded constants
        — 0.7 for every API hit, 0.65 for every browser hit — which made it
        first-source-wins with a scoring function painted on, and left a
        docstring promising the re-rank that never arrived (F10).

        The model is allowed to reject the whole list. A dataset that does not
        contain the measured quantity is worse than no dataset: it produces a
        generated script that runs, returns a number, and answers a different
        question.
        """
        if not candidates:
            return None

        listing = "\n".join(
            f"{i + 1}. [{c['source']}] {c.get('title', '')[:120]}\n"
            f"   {c['url'][:140]}\n"
            f"   {c.get('description', '')[:160]}"
            for i, c in enumerate(candidates[:12])
        )
        prompt = (
            "A quantitative claim needs checking against raw data. Pick the "
            "candidate dataset that could actually settle it.\n\n"
            f"Claim: {claim_text[:600]}\n\n"
            f"Candidates:\n{listing}\n\n"
            "A dataset only qualifies if it plausibly contains the specific "
            "quantity the claim measures, for the right population and period. "
            "Reject the list if none does — a wrong dataset yields a confident "
            "answer to a different question.\n\n"
            'Return JSON: {"index": 1-N or null, "confidence": 0.0-1.0, '
            '"reasoning": "one sentence"}'
        )
        try:
            result = self.llm_client.call_llm(
                prompt,
                response_format="json",
                task_name="dataset_reranking",
                system_message="You are a data analyst matching datasets to claims.",
            )
        except Exception as e:
            logger.warning(f"  Dataset re-rank failed ({e}); falling back to score order")
            return max(candidates, key=lambda x: x.get("score", 0))

        idx = (result or {}).get("index")
        confidence = float((result or {}).get("confidence") or 0.0)
        if not isinstance(idx, int) or not (1 <= idx <= min(len(candidates), 12)):
            logger.info(
                f"  LLM rejected all {len(candidates)} dataset candidates: "
                f"{(result or {}).get('reasoning', 'no reason given')}"
            )
            return None
        if confidence < MIN_RELEVANCE_SCORE:
            logger.info(
                f"  Best dataset candidate scored {confidence:.2f}, below the "
                f"{MIN_RELEVANCE_SCORE} relevance floor — treating as no source"
            )
            return None

        chosen = dict(candidates[idx - 1])
        chosen["score"] = confidence
        logger.info(
            f"  Re-ranked to [{chosen['source']}] {chosen['url'][:80]} "
            f"(confidence {confidence:.2f})"
        )
        return chosen
