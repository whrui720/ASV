"""Text Finder - Search for text sources for qualitative claims"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from hybrid_citation_scraper.llm_client import LLMClient
from run_paths import RunPaths

logger = logging.getLogger(__name__)


class TextFinder:
    """Search for text-based sources for qualitative claims via browser (Google Scholar)."""

    def __init__(
        self,
        llm_client: LLMClient,
        browser_searcher=None,
        run_paths: Optional[RunPaths] = None,
    ):
        self.llm_client = llm_client
        self.browser_searcher = browser_searcher
        self.run_paths = run_paths
        self.found_text_sources: List[Dict[str, Any]] = []

    def find_text_source(self, claim_text: str, claim_id: str) -> Optional[Dict[str, Any]]:
        """
        Search for text-based sources via Google Scholar using the browser searcher.
        Returns best matching source URL + metadata, or None if nothing found.
        """
        if self.browser_searcher is None:
            logger.warning(
                f"[{claim_id}] No browser_searcher available for text source search — "
                "set TextFinder.browser_searcher before calling find_text_source()"
            )
            return None

        logger.info(f"[{claim_id}] Searching Google Scholar via browser: {claim_text[:80]}...")
        query = claim_text[:200]

        try:
            urls = self.browser_searcher.search_google_scholar(query, top_k=3)
        except Exception as e:
            logger.warning(f"[{claim_id}] Browser search failed: {e}")
            return None

        if not urls:
            logger.info(f"[{claim_id}] No text sources found via browser search")
            return None

        best_url = urls[0]
        logger.info(f"[{claim_id}] ✓ Text source found: {best_url}")
        result = {
            "url": best_url,
            "title": f"Source for: {claim_text[:60]}...",
            "source": "google_scholar_browser",
            "relevance_score": 0.8,
            "found_by_claim_id": claim_id,
            "all_candidates": urls,
        }
        self.found_text_sources.append(result)
        return result

    def save_discovery_records(self) -> Optional[Path]:
        """Flush in-memory text-source discoveries to the run's sourcefinder folder."""
        if self.run_paths is None:
            return None
        path = self.run_paths.found_text_sources_json()
        payload = {
            "run_timestamp": datetime.now().isoformat(),
            "pdf_stem": self.run_paths.pdf_stem,
            "count": len(self.found_text_sources),
            "text_sources": self.found_text_sources,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        return path
