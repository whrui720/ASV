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
from typing import Optional, Dict, Any
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

    When llm_client is provided, the finder will parse bibliography-formatted citation
    strings into structured fields (title, first_author, year, doi) before searching,
    which dramatically improves hit rates for refs lacking inline DOIs.
    """

    def __init__(self, llm_client=None):
        self.llm_client = llm_client
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

        # Cache LLM-parsed citation structure across batches so we don't re-parse
        # the same bibliography string once per claim in the batch.
        self._parse_cache: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def find_url(self, raw_citation_text: str) -> Optional[str]:
        """
        Given a raw citation string (e.g. 'Smith J. J Virol 1999;73:3210. doi:10.1128/xxx'),
        return a URL pointing to the full text, or None if not found.

        Resolution cascade:
          1. Regex DOI → Unpaywall / Semantic Scholar / CrossRef
          2. LLM-parsed DOI (catches DOIs the regex misses) → same three APIs
          3. LLM-parsed title → Semantic Scholar text search (also recovers DOI of
             non-OA hits and feeds it back into Unpaywall/CrossRef)
          4. Browser fallback (Google Scholar) using LLM-built query
        """
        # Parse once, reuse below.
        parsed = self._parse_citation_with_llm(raw_citation_text)

        # 1. Regex-extracted DOI (cheapest, no LLM cost).
        doi = _extract_doi(raw_citation_text)
        url = None
        if doi:
            logger.info(f"  DOI extracted (regex): {doi}")
            url = (
                self._try_unpaywall(doi)
                or self._try_semantic_scholar_by_doi(doi)
                or self._try_crossref(doi)
            )

        # 2. LLM-parsed DOI (when regex missed it — often present as 'doi: 10.x/y'
        #    with non-standard separators).
        if not url and parsed.get("doi") and parsed["doi"] != doi:
            doi2 = parsed["doi"]
            logger.info(f"  DOI extracted (LLM): {doi2}")
            url = (
                self._try_unpaywall(doi2)
                or self._try_semantic_scholar_by_doi(doi2)
                or self._try_crossref(doi2)
            )

        # 3. Title-based Semantic Scholar search. May recover a DOI even when the
        #    paper has no OA PDF — we retry the DOI-based APIs in that case.
        if not url:
            title_query = parsed.get("title") or raw_citation_text
            ss_url, ss_doi = self._try_semantic_scholar_by_text(title_query)
            url = ss_url
            if not url and ss_doi and ss_doi != doi and ss_doi != parsed.get("doi"):
                logger.info(f"  Semantic Scholar surfaced DOI: {ss_doi} — retrying OA APIs")
                url = self._try_unpaywall(ss_doi) or self._try_crossref(ss_doi)

        # 3b. CrossRef bibliographic resolver — converts a parsed citation into a DOI
        #     when neither inline regex nor Semantic Scholar found one. Free, no key,
        #     and critical for the no-DOI old-medical-ref case (Semantic Scholar
        #     aggressively rate-limits unkeyed clients with 429s).
        if not url:
            cr_doi = self._resolve_doi_via_crossref(parsed, raw_citation_text)
            if cr_doi and cr_doi != doi and cr_doi != parsed.get("doi"):
                logger.info(f"  CrossRef bibliographic surfaced DOI: {cr_doi} — retrying OA APIs")
                url = self._try_unpaywall(cr_doi) or self._try_crossref(cr_doi)

        # 4. Browser fallback: Google Scholar. Build a tight query — '"title" author year' —
        #    much more Scholar-friendly than dumping the full bibliography string.
        if not url and self.browser_searcher is not None:
            scholar_query = self._build_scholar_query(parsed, raw_citation_text)
            logger.info(f"  APIs exhausted — trying Google Scholar via browser: {scholar_query!r}")
            try:
                results = self.browser_searcher.search_google_scholar(scholar_query, top_k=3)
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

    # ------------------------------------------------------------------
    # LLM-based citation parsing
    # ------------------------------------------------------------------

    def _parse_citation_with_llm(self, raw_text: str) -> Dict[str, Any]:
        """
        Parse a bibliography-formatted citation string into {title, first_author, year, journal, doi}.
        Cached per raw_text so batched claims sharing one citation don't re-parse.

        Returns an empty dict if no llm_client was provided or the LLM call fails — callers
        must handle missing fields gracefully (the resolution cascade in find_url does).
        """
        if not raw_text:
            return {}
        if raw_text in self._parse_cache:
            return self._parse_cache[raw_text]
        if self.llm_client is None:
            self._parse_cache[raw_text] = {}
            return {}

        prompt = (
            "Parse the following bibliography citation into structured fields. "
            "Return JSON with keys: title, first_author, year, journal, doi. "
            "Use null for any field you cannot determine. The title should be the "
            "paper/article title only (no author or journal). first_author is the "
            "surname of the first listed author. year is a 4-digit integer or null.\n\n"
            f"Citation: {raw_text}\n\n"
            'Example output: {"title": "Gene delivery using herpes simplex virus vectors", '
            '"first_author": "Burton", "year": 2002, "journal": "DNA Cell Biol", "doi": null}'
        )
        try:
            result = self.llm_client.call_llm(
                prompt,
                response_format="json",
                task_name="reference_parsing",
                system_message="You parse academic citation strings into structured fields.",
            )
            if not isinstance(result, dict):
                result = {}
        except Exception as e:
            logger.debug(f"  Citation parse failed: {e}")
            result = {}

        self._parse_cache[raw_text] = result
        return result

    def _resolve_doi_via_crossref(
        self, parsed: Dict[str, Any], raw_fallback: str
    ) -> Optional[str]:
        """
        Use CrossRef's bibliographic search to resolve a citation string to a DOI.
        Builds a tight 'query.bibliographic' string from LLM-parsed fields when available,
        falls back to the raw citation otherwise. Returns the top hit's DOI or None.

        CrossRef is free, requires no API key, and indexes ~140M scholarly works.
        """
        if parsed.get("title"):
            parts = [parsed["title"]]
            if parsed.get("first_author"):
                parts.append(str(parsed["first_author"]))
            if parsed.get("year"):
                parts.append(str(parsed["year"]))
            query = " ".join(parts)
        else:
            query = raw_fallback[:200]

        try:
            resp = self._session.get(
                "https://api.crossref.org/works",
                params={"query.bibliographic": query, "rows": 1},
                timeout=DOWNLOAD_TIMEOUT,
            )
            if resp.status_code in (400, 404):
                return None
            resp.raise_for_status()
            items = resp.json().get("message", {}).get("items", [])
            if not items:
                return None
            return items[0].get("DOI")
        except Exception as e:
            logger.debug(f"  CrossRef bibliographic error: {e}")
            return None

    @staticmethod
    def _build_scholar_query(parsed: Dict[str, Any], raw_fallback: str) -> str:
        """Compose a Scholar-friendly query from parsed fields; fall back to raw text."""
        title = parsed.get("title")
        author = parsed.get("first_author")
        year = parsed.get("year")
        if title:
            parts = [f'"{title}"']
            if author:
                parts.append(str(author))
            if year:
                parts.append(str(year))
            return " ".join(parts)
        return raw_fallback[:200]

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

    def _try_semantic_scholar_by_text(self, raw_text: str) -> "tuple[Optional[str], Optional[str]]":
        """
        Title-based search when no DOI is available.

        Returns (oa_pdf_url, recovered_doi). Either may be None.
        The recovered DOI is useful even when no OA PDF is published — callers can
        retry Unpaywall / CrossRef with it.
        """
        if not raw_text or len(raw_text) < 10:
            return None, None
        # Use first 150 chars as query — enough to capture author/year/title
        query = raw_text[:150]
        try:
            resp = self._session.get(
                f"{SEMANTIC_SCHOLAR_API}/paper/search",
                params={"query": query, "fields": "openAccessPdf,externalIds", "limit": 3},
                timeout=DOWNLOAD_TIMEOUT,
            )
            if resp.status_code in (400, 404):
                return None, None
            resp.raise_for_status()
            data = resp.json()
            recovered_doi: Optional[str] = None
            for paper in data.get("data", []):
                oa = paper.get("openAccessPdf") or {}
                url = oa.get("url")
                ext = paper.get("externalIds") or {}
                if recovered_doi is None and ext.get("DOI"):
                    recovered_doi = ext["DOI"]
                if url:
                    logger.debug(f"  Semantic Scholar text-search hit: {url}")
                    return url, recovered_doi
            return None, recovered_doi
        except Exception as e:
            logger.debug(f"  Semantic Scholar (text) error: {e}")
            return None, None
