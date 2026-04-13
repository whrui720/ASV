"""Text Finder - Search for text sources for qualitative claims"""

import logging
from typing import Optional, Dict, Any

from hybrid_citation_scraper.llm_client import LLMClient

logger = logging.getLogger(__name__)


class TextFinder:
    """Search for text-based sources for qualitative claims via browser (Google Scholar)."""

    def __init__(self, llm_client: LLMClient, browser_searcher=None):
        self.llm_client = llm_client
        self.browser_searcher = browser_searcher

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
        return {
            "url": best_url,
            "title": f"Source for: {claim_text[:60]}...",
            "source": "google_scholar_browser",
            "relevance_score": 0.8,
            "all_candidates": urls,
        }
