"""
Academic Paper Finder — resolves citations to downloadable URLs.

Resolution cascade (each step is tried only if the previous returned nothing):
  1. Unpaywall API       (DOI required, UNPAYWALL_EMAIL recommended)
  2. Semantic Scholar    (DOI or title search)
  3. CrossRef            (DOI, returns PDF links when publisher provides them)

Cookie-based institutional auth fallback:
  Set INSTITUTIONAL_COOKIES in .env as a JSON string:
      {"www.jstor.org": {"SessionID": "abc123"}, "www.nature.com": {"access_token": "xyz"}}
  When a URL is found but requires a login, fetch_with_cookies() will attempt
  to use the matching domain's cookies from that dict.
"""

import json
import logging
import re
import requests
from typing import Optional, Dict
from urllib.parse import urlparse

from .config import (
    UNPAYWALL_API,
    SEMANTIC_SCHOLAR_API,
    CROSSREF_API,
    UNPAYWALL_EMAIL,
    SEMANTIC_SCHOLAR_API_KEY,
    INSTITUTIONAL_COOKIES,
    DOWNLOAD_TIMEOUT,
)

logger = logging.getLogger(__name__)

_DOI_RE = re.compile(r'\b(10\.\d{4,}/\S+?)(?:[,\s\])}]|$)', re.IGNORECASE)


def _extract_doi(text: str) -> Optional[str]:
    """Extract first DOI found in raw citation text."""
    if not text:
        return None
    m = _DOI_RE.search(text)
    return m.group(1).rstrip(".") if m else None


class AcademicPaperFinder:
    """
    Resolves a raw citation string (or DOI) to a publicly accessible PDF/HTML URL.
    Tries open-access APIs first; falls back to browser search (Google Scholar) if set.
    """

    def __init__(self):
        self.browser_searcher = None  # injected by orchestrator after startup login
        self._session = requests.Session()
        self._session.headers["User-Agent"] = (
            "ASV-pipeline/1.0 (academic source validation; contact via project repo)"
        )
        if SEMANTIC_SCHOLAR_API_KEY:
            self._session.headers["x-api-key"] = SEMANTIC_SCHOLAR_API_KEY

        # Parse institutional cookies once at startup
        self._inst_cookies: Dict[str, Dict[str, str]] = {}
        if INSTITUTIONAL_COOKIES:
            try:
                self._inst_cookies = json.loads(INSTITUTIONAL_COOKIES)
                logger.info(
                    f"Institutional cookies loaded for domains: {list(self._inst_cookies.keys())}"
                )
            except json.JSONDecodeError as e:
                logger.warning(f"INSTITUTIONAL_COOKIES is not valid JSON: {e}")

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def find_url(self, raw_citation_text: str) -> Optional[str]:
        """
        Given a raw citation string (e.g. 'Smith J. J Virol 1999;73:3210. doi:10.1128/xxx'),
        return a URL pointing to the full text, or None if not found.
        """
        doi = _extract_doi(raw_citation_text)
        url = None

        if doi:
            logger.info(f"  DOI extracted: {doi}")
            url = (
                self._try_unpaywall(doi)
                or self._try_semantic_scholar_by_doi(doi)
                or self._try_crossref(doi)
            )

        if not url:
            # Title-based fallback using Semantic Scholar search
            url = self._try_semantic_scholar_by_text(raw_citation_text)

        # Browser fallback: Google Scholar search
        if not url and self.browser_searcher is not None:
            logger.info("  APIs exhausted — trying Google Scholar via browser")
            try:
                results = self.browser_searcher.search_google_scholar(raw_citation_text[:200], top_k=3)
                if results:
                    url = results[0]
                    logger.info(f"  Browser fallback hit: {url}")
            except Exception as e:
                logger.warning(f"  Browser fallback failed: {e}")

        if url:
            logger.info(f"  ✓ Resolved URL: {url}")
        else:
            logger.info("  ✗ No URL found (APIs + browser exhausted)")

        return url

    def fetch_with_cookies(self, url: str, timeout: int = DOWNLOAD_TIMEOUT) -> Optional[bytes]:
        """
        Attempt to download content at *url* using institutional cookies for the
        matching domain.  Returns raw bytes on success, None on failure.
        """
        domain = urlparse(url).netloc
        cookies = self._inst_cookies.get(domain, {})
        if not cookies:
            logger.debug(f"No institutional cookies configured for {domain}")
            return None

        try:
            logger.info(f"  Trying institutional cookies for {domain} ...")
            resp = self._session.get(url, cookies=cookies, timeout=timeout)
            resp.raise_for_status()
            # Quick sanity check: if we got an HTML login page instead of content, bail
            ct = resp.headers.get("content-type", "")
            if "text/html" in ct and b"login" in resp.content[:4096].lower():
                logger.warning("  Cookies present but server returned a login page — may be expired")
                return None
            logger.info(f"  ✓ Institutional download succeeded ({len(resp.content)} bytes)")
            return resp.content
        except Exception as e:
            logger.warning(f"  Institutional cookie fetch failed: {e}")
            return None

    # ------------------------------------------------------------------
    # Resolution steps
    # ------------------------------------------------------------------

    def _try_unpaywall(self, doi: str) -> Optional[str]:
        if not UNPAYWALL_EMAIL:
            logger.debug("UNPAYWALL_EMAIL not set; skipping Unpaywall")
            return None
        try:
            resp = self._session.get(
                f"{UNPAYWALL_API}/{doi}",
                params={"email": UNPAYWALL_EMAIL},
                timeout=DOWNLOAD_TIMEOUT,
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()
            loc = data.get("best_oa_location") or {}
            url = loc.get("url_for_pdf") or loc.get("url_for_landing_page")
            if url:
                logger.debug(f"  Unpaywall hit: {url}")
            return url
        except Exception as e:
            logger.debug(f"  Unpaywall error: {e}")
            return None

    def _try_semantic_scholar_by_doi(self, doi: str) -> Optional[str]:
        try:
            resp = self._session.get(
                f"{SEMANTIC_SCHOLAR_API}/paper/DOI:{doi}",
                params={"fields": "openAccessPdf,externalIds"},
                timeout=DOWNLOAD_TIMEOUT,
            )
            if resp.status_code in (404, 400):
                return None
            resp.raise_for_status()
            data = resp.json()
            oa = data.get("openAccessPdf") or {}
            url = oa.get("url")
            if url:
                logger.debug(f"  Semantic Scholar hit: {url}")
            return url
        except Exception as e:
            logger.debug(f"  Semantic Scholar (DOI) error: {e}")
            return None

    def _try_crossref(self, doi: str) -> Optional[str]:
        try:
            resp = self._session.get(
                f"{CROSSREF_API}/{doi}",
                timeout=DOWNLOAD_TIMEOUT,
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()
            links = data.get("message", {}).get("link", [])
            for link in links:
                ct = link.get("content-type", "")
                if "pdf" in ct or "pdf" in link.get("URL", "").lower():
                    url = link["URL"]
                    logger.debug(f"  CrossRef hit: {url}")
                    return url
            # No PDF link — return landing page if available
            url = data.get("message", {}).get("URL")
            return url
        except Exception as e:
            logger.debug(f"  CrossRef error: {e}")
            return None

    def _try_semantic_scholar_by_text(self, raw_text: str) -> Optional[str]:
        """Title-based search when no DOI is available."""
        if not raw_text or len(raw_text) < 10:
            return None
        # Use first 150 chars as query — enough to capture author/year/title
        query = raw_text[:150]
        try:
            resp = self._session.get(
                f"{SEMANTIC_SCHOLAR_API}/paper/search",
                params={"query": query, "fields": "openAccessPdf", "limit": 3},
                timeout=DOWNLOAD_TIMEOUT,
            )
            if resp.status_code in (400, 404):
                return None
            resp.raise_for_status()
            data = resp.json()
            for paper in data.get("data", []):
                oa = paper.get("openAccessPdf") or {}
                url = oa.get("url")
                if url:
                    logger.debug(f"  Semantic Scholar text-search hit: {url}")
                    return url
            return None
        except Exception as e:
            logger.debug(f"  Semantic Scholar (text) error: {e}")
            return None
