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
        """Return the best single candidate URL, or None. Thin wrapper over find_urls."""
        urls = self.find_urls(raw_citation_text)
        return urls[0] if urls else None

    def find_urls(self, raw_citation_text: str) -> list[str]:
        """
        Return a ranked list of candidate URLs. Repository/PDF mirrors (PMC, arXiv,
        institutional repos) are surfaced ahead of publisher landing pages so callers
        can iterate on 401/403 without giving up on paywalled hits.

        Resolution cascade (stops at the first step producing candidates):
          1. Regex DOI → Unpaywall / Semantic Scholar / CrossRef
          2. LLM-parsed DOI (catches DOIs the regex misses) → same three APIs
          3. LLM-parsed title → Semantic Scholar text search (also recovers DOI of
             non-OA hits and feeds it back into Unpaywall/CrossRef)
          4. Browser fallback (Google Scholar) using LLM-built query
        """
        parsed = self._parse_citation_with_llm(raw_citation_text)

        candidates: list[str] = []

        # 1. Regex-extracted DOI (cheapest, no LLM cost).
        doi = _extract_doi(raw_citation_text)
        if doi:
            logger.info(f"  DOI extracted (regex): {doi}")
            candidates = self._resolve_from_doi(doi)

        # 2. LLM-parsed DOI (when regex missed it).
        if not candidates and parsed.get("doi") and parsed["doi"] != doi:
            doi2 = parsed["doi"]
            logger.info(f"  DOI extracted (LLM): {doi2}")
            candidates = self._resolve_from_doi(doi2)

        # 3. Title-based Semantic Scholar search.
        if not candidates:
            title_query = parsed.get("title") or raw_citation_text
            ss_urls, ss_doi = self._try_semantic_scholar_by_text(title_query)
            candidates = list(ss_urls)
            if not candidates and ss_doi and ss_doi != doi and ss_doi != parsed.get("doi"):
                logger.info(f"  Semantic Scholar surfaced DOI: {ss_doi} — retrying OA APIs")
                candidates = self._resolve_from_doi(ss_doi, skip_ss=True)

        # 3b. CrossRef bibliographic resolver.
        if not candidates:
            cr_doi = self._resolve_doi_via_crossref(parsed, raw_citation_text)
            if cr_doi and cr_doi != doi and cr_doi != parsed.get("doi"):
                logger.info(f"  CrossRef bibliographic surfaced DOI: {cr_doi} — retrying OA APIs")
                candidates = self._resolve_from_doi(cr_doi)

        # 4. Browser fallback: Google Scholar.
        if not candidates and self.browser_searcher is not None:
            scholar_query = self._build_scholar_query(parsed, raw_citation_text)
            logger.info(f"  APIs exhausted — trying Google Scholar via browser: {scholar_query!r}")
            try:
                results = self.browser_searcher.search_google_scholar(scholar_query, top_k=3)
                if results:
                    candidates = list(results)
                    logger.info(f"  Browser fallback: {len(candidates)} candidate(s)")
            except Exception as e:
                logger.warning(f"  Browser fallback failed: {e}")

        candidates = self._dedupe_preserve_order(candidates)

        if candidates:
            logger.info(f"  ✓ Resolved {len(candidates)} candidate URL(s): {candidates[0]}"
                        + (f" (+{len(candidates)-1} fallback)" if len(candidates) > 1 else ""))
        else:
            logger.info("  ✗ No URL found (APIs + browser exhausted)")

        return candidates

    def _resolve_from_doi(self, doi: str, *, skip_ss: bool = False) -> list[str]:
        """
        Merge Unpaywall + Semantic-Scholar-by-DOI + CrossRef candidates for one DOI.
        Unpaywall goes first because it surfaces repository mirrors (PMC/arXiv) that
        skip publisher paywalls; SS/CrossRef fill in when Unpaywall lacks OA data.
        """
        out: list[str] = []
        out.extend(self._try_unpaywall(doi))
        if not skip_ss:
            out.extend(self._try_semantic_scholar_by_doi(doi))
        out.extend(self._try_crossref(doi))
        return out

    @staticmethod
    def _dedupe_preserve_order(urls: list[str]) -> list[str]:
        seen = set()
        out = []
        for u in urls:
            if u and u not in seen:
                seen.add(u)
                out.append(u)
        return out

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

    # Publisher domains that routinely reject unauthenticated requests. Ranked
    # last so we try repository/preprint mirrors first.
    _PAYWALL_HOSTS = (
        "wiley.com", "onlinelibrary.wiley.com",
        "sciencedirect.com", "elsevier.com",
        "springer.com", "link.springer.com",
        "nature.com",
        "tandfonline.com",
        "sagepub.com", "journals.sagepub.com",
        "jamanetwork.com",
        "cell.com",
        "science.org",
        "asm.org", "journals.asm.org",
        "pnas.org",
        "oup.com", "academic.oup.com",
    )

    @classmethod
    def _is_paywall_host(cls, url: str) -> bool:
        try:
            host = urlparse(url).netloc.lower()
        except Exception:
            return False
        return any(host.endswith(p) for p in cls._PAYWALL_HOSTS)

    def _try_unpaywall(self, doi: str) -> list[str]:
        """
        Return all Unpaywall OA candidates for a DOI, ranked so repository mirrors
        (PMC, arXiv, institutional repos) come before publisher URLs and PDFs come
        before landing pages. Publisher URLs are still included as a last resort.
        """
        if not UNPAYWALL_EMAIL:
            logger.debug("UNPAYWALL_EMAIL not set; skipping Unpaywall")
            return []
        try:
            resp = self._session.get(
                f"{UNPAYWALL_API}/{doi}",
                params={"email": UNPAYWALL_EMAIL},
                timeout=DOWNLOAD_TIMEOUT,
            )
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.debug(f"  Unpaywall error: {e}")
            return []

        locations = data.get("oa_locations") or []
        # Rank: repository host_type first, then PDF over landing.
        def rank(loc):
            is_repo = 0 if loc.get("host_type") == "repository" else 1
            has_pdf = 0 if loc.get("url_for_pdf") else 1
            return (is_repo, has_pdf)

        sorted_locs = sorted(locations, key=rank)

        urls: list[str] = []
        for loc in sorted_locs:
            for key in ("url_for_pdf", "url_for_landing_page", "url"):
                u = loc.get(key)
                if u:
                    urls.append(u)
                    break

        # Fall back to best_oa_location if oa_locations was empty
        if not urls:
            loc = data.get("best_oa_location") or {}
            u = loc.get("url_for_pdf") or loc.get("url_for_landing_page")
            if u:
                urls.append(u)

        if urls:
            logger.debug(f"  Unpaywall: {len(urls)} candidate(s); top={urls[0]}")
        return urls

    def _try_semantic_scholar_by_doi(self, doi: str) -> list[str]:
        try:
            resp = self._session.get(
                f"{SEMANTIC_SCHOLAR_API}/paper/DOI:{doi}",
                params={"fields": "openAccessPdf,externalIds"},
                timeout=DOWNLOAD_TIMEOUT,
            )
            if resp.status_code in (404, 400):
                return []
            resp.raise_for_status()
            data = resp.json()
            oa = data.get("openAccessPdf") or {}
            url = oa.get("url")
            if url:
                logger.debug(f"  Semantic Scholar hit: {url}")
                return [url]
            return []
        except Exception as e:
            logger.debug(f"  Semantic Scholar (DOI) error: {e}")
            return []

    def _try_crossref(self, doi: str) -> list[str]:
        try:
            resp = self._session.get(
                f"{CROSSREF_API}/{doi}",
                timeout=DOWNLOAD_TIMEOUT,
            )
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.debug(f"  CrossRef error: {e}")
            return []

        urls: list[str] = []
        for link in data.get("message", {}).get("link", []):
            ct = link.get("content-type", "")
            u = link.get("URL")
            if u and ("pdf" in ct or "pdf" in u.lower()):
                urls.append(u)

        # Include landing page URL as a lower-priority fallback.
        landing = data.get("message", {}).get("URL")
        if landing and landing not in urls:
            urls.append(landing)

        if urls:
            logger.debug(f"  CrossRef: {len(urls)} candidate(s)")
        return urls

    def _try_semantic_scholar_by_text(
        self, raw_text: str
    ) -> "tuple[list[str], Optional[str]]":
        """
        Title-based search when no DOI is available.

        Returns (oa_pdf_urls, recovered_doi). The list may be empty; the DOI is
        useful even when no OA PDF is published — callers can retry Unpaywall / CrossRef with it.
        """
        if not raw_text or len(raw_text) < 10:
            return [], None
        query = raw_text[:150]
        try:
            resp = self._session.get(
                f"{SEMANTIC_SCHOLAR_API}/paper/search",
                params={"query": query, "fields": "openAccessPdf,externalIds", "limit": 3},
                timeout=DOWNLOAD_TIMEOUT,
            )
            if resp.status_code in (400, 404):
                return [], None
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.debug(f"  Semantic Scholar (text) error: {e}")
            return [], None

        recovered_doi: Optional[str] = None
        urls: list[str] = []
        for paper in data.get("data", []):
            oa = paper.get("openAccessPdf") or {}
            url = oa.get("url")
            ext = paper.get("externalIds") or {}
            if recovered_doi is None and ext.get("DOI"):
                recovered_doi = ext["DOI"]
            if url:
                urls.append(url)
        if urls:
            logger.debug(f"  Semantic Scholar text-search: {len(urls)} candidate(s)")
        return urls, recovered_doi
