"""
Browser-based source search using Playwright.

Used as a fallback when API-based finders return no results or encounter paywalls.
Also handles the human-in-the-loop login flow: the browser opens in non-headless mode
so the user can log in to paywalled sites manually before the pipeline proceeds.

Agentic link selection: instead of hardcoding CSS selectors (which break when sites
redesign), the raw links extracted from each search results page are passed to the LLM,
which picks the most relevant one for the current query.
"""

import logging
import urllib.parse
from typing import Optional

from bs4 import BeautifulSoup

from .config import (
    BROWSER_HEADLESS,
    BROWSER_SEARCH_TIMEOUT,
    GOOGLE_SCHOLAR_URL,
    ZENODO_SEARCH_URL,
    FIGSHARE_SEARCH_URL,
    HUGGINGFACE_DATASETS_URL,
)

logger = logging.getLogger(__name__)

# Domains to skip when collecting candidate links from a search page
_SKIP_DOMAINS = {
    "google.com", "gstatic.com", "googleapis.com",
    "w3.org", "schema.org", "facebook.com", "twitter.com",
}


class BrowserSearcher:
    """
    Playwright-backed searcher with LLM-guided link selection.

    Lazy-initialised: the browser process is not started until the first search or
    open_domains() call, so importing this class has no side effects.
    """

    def __init__(self, llm_client, headless: bool = BROWSER_HEADLESS):
        self.llm_client = llm_client
        self.headless = headless
        self._playwright = None
        self._browser = None
        self._context = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _require_context(self):
        """Ensure the browser is started and return the (non-None) browser context."""
        self._ensure_started()
        assert self._context is not None
        return self._context

    def _ensure_started(self) -> None:
        """Start the Playwright browser if it hasn't been started yet."""
        if self._browser is not None:
            return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise RuntimeError(
                "playwright is not installed. Run: pip install playwright && playwright install chromium"
            )
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self.headless)
        self._context = self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        )
        logger.info(f"Playwright Chromium started (headless={self.headless})")

    def close(self) -> None:
        """Shut down the browser and Playwright instance."""
        if self._browser:
            try:
                self._browser.close()
            except Exception:
                pass
        if self._playwright:
            try:
                self._playwright.stop()
            except Exception:
                pass
        self._browser = None
        self._context = None
        self._playwright = None
        logger.info("Playwright browser closed")

    # ------------------------------------------------------------------
    # Human login flow
    # ------------------------------------------------------------------

    def open_domains(self, domains: list[str]) -> None:
        """
        Open each domain in a separate browser tab so the user can log in manually.
        The browser window must be visible (headless=False) for this to work.
        After calling this, the caller should prompt the user to complete login and
        press Enter before continuing.
        """
        context = self._require_context()
        for domain in domains:
            url = f"https://{domain}"
            try:
                page = context.new_page()
                page.goto(url, timeout=BROWSER_SEARCH_TIMEOUT, wait_until="domcontentloaded")
                logger.info(f"Opened login tab: {url}")
            except Exception as e:
                logger.warning(f"Could not open {url}: {e}")

    # ------------------------------------------------------------------
    # Search methods
    # ------------------------------------------------------------------

    def search_google_scholar(self, query: str, top_k: int = 5) -> list[str]:
        """
        Search Google Scholar and return up to top_k paper URLs ranked by LLM.

        Note: Google Scholar may show a CAPTCHA. Since the browser is non-headless,
        the user can solve it manually if it appears.
        """
        url = GOOGLE_SCHOLAR_URL + urllib.parse.quote_plus(query)
        return self._search_page(url, query, top_k, source_label="Google Scholar")

    def search_zenodo(self, query: str, top_k: int = 5) -> list[str]:
        """Search Zenodo for datasets/records and return up to top_k URLs."""
        url = ZENODO_SEARCH_URL + urllib.parse.quote_plus(query)
        return self._search_page(url, query, top_k, source_label="Zenodo")

    def search_figshare(self, query: str, top_k: int = 5) -> list[str]:
        """Search Figshare for datasets and return up to top_k URLs."""
        url = FIGSHARE_SEARCH_URL + urllib.parse.quote_plus(query)
        return self._search_page(url, query, top_k, source_label="Figshare")

    def search_huggingface_datasets(self, query: str, top_k: int = 5) -> list[str]:
        """Search HuggingFace Datasets and return up to top_k dataset URLs."""
        url = HUGGINGFACE_DATASETS_URL + urllib.parse.quote_plus(query)
        return self._search_page(url, query, top_k, source_label="HuggingFace Datasets")

    # ------------------------------------------------------------------
    # Page utilities
    # ------------------------------------------------------------------

    def get_page_text(self, url: str) -> Optional[str]:
        """
        Load a URL and return its visible text content.
        Returns None on failure (e.g. paywall, timeout, error).
        """
        context = self._require_context()
        page = context.new_page()
        try:
            page.goto(url, timeout=BROWSER_SEARCH_TIMEOUT, wait_until="domcontentloaded")
            text = page.inner_text("body")
            logger.info(f"  get_page_text: retrieved {len(text)} chars from {url}")
            return text
        except Exception as e:
            logger.warning(f"  get_page_text failed for {url}: {e}")
            return None
        finally:
            page.close()

    def export_cookies(self) -> list[dict]:
        """
        Return all cookies currently stored in the browser context. Used by the
        orchestrator after the human-login checkpoint to bridge the just-acquired
        session into every ``requests.Session`` in the pipeline — closes the gap
        between "user logged in via Playwright" and "downloads happen via requests".

        Returns an empty list when the browser hasn't been started yet.
        """
        if self._context is None:
            return []
        try:
            return [dict(c) for c in self._context.cookies()]
        except Exception as e:
            logger.warning(f"  export_cookies failed: {e}")
            return []

    def download_url(self, url: str, timeout_ms: Optional[int] = None) -> Optional[bytes]:
        """
        Fetch *url* via Playwright's ``APIRequestContext`` and return the raw body
        as bytes. Because ``context.request`` shares storage state with the
        browser context, any cookies the user set during manual login apply
        automatically — this is what makes the login flow actually pay off at
        download time.

        Returns None on non-2xx responses, timeouts, or network errors. Callers
        should treat the return value the same as a failed ``requests.get``.
        """
        context = self._require_context()
        # Playwright timeouts are in milliseconds; default to the browser timeout
        # (30s) which is a reasonable ceiling for a single publisher fetch.
        timeout = timeout_ms if timeout_ms is not None else BROWSER_SEARCH_TIMEOUT
        try:
            resp = context.request.get(url, timeout=timeout)
        except Exception as e:
            logger.warning(f"  Playwright download failed for {url}: {e}")
            return None
        if not resp.ok:
            logger.info(f"  Playwright download {url}: HTTP {resp.status}")
            return None
        try:
            body = resp.body()
        except Exception as e:
            logger.warning(f"  Playwright response body read failed for {url}: {e}")
            return None
        logger.info(f"  ✓ Playwright download succeeded ({len(body)} bytes) from {url}")
        return body

    def is_paywalled(self, url: str) -> bool:
        """
        Return True if the page appears to require login / subscription to read.
        Uses a lightweight heuristic: redirect to login URL or paywall keyword in body.
        """
        context = self._require_context()
        page = context.new_page()
        try:
            page.goto(url, timeout=BROWSER_SEARCH_TIMEOUT, wait_until="domcontentloaded")
            current_url = page.url.lower()
            if any(kw in current_url for kw in ("login", "signin", "sign-in", "subscribe")):
                return True
            snippet = page.inner_text("body")[:2000].lower()
            paywall_phrases = [
                "sign in to read", "subscribe to access", "log in to view",
                "purchase access", "institutional access", "full access required",
                "create a free account", "register to continue",
            ]
            return any(phrase in snippet for phrase in paywall_phrases)
        except Exception as e:
            logger.debug(f"is_paywalled check failed for {url}: {e}")
            return False
        finally:
            page.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _search_page(
        self, search_url: str, query: str, top_k: int, source_label: str
    ) -> list[str]:
        """
        Navigate to a search results URL, extract candidate links, ask the LLM to
        rank them, and return the top_k most relevant URLs.
        """
        context = self._require_context()
        page = context.new_page()
        try:
            logger.info(f"  Browser searching {source_label}: {search_url}")
            page.goto(search_url, timeout=BROWSER_SEARCH_TIMEOUT, wait_until="domcontentloaded")
            candidates = self._extract_candidate_links(page)
        except Exception as e:
            logger.warning(f"  {source_label} browser search failed: {e}")
            return []
        finally:
            page.close()

        if not candidates:
            logger.info(f"  {source_label}: no candidate links found")
            return []

        logger.info(f"  {source_label}: {len(candidates)} candidate links found; asking LLM to rank")
        ranked = self._rank_links_with_llm(query, candidates, top_k)
        logger.info(f"  {source_label}: LLM returned {len(ranked)} ranked URLs")
        return ranked

    def _extract_candidate_links(self, page) -> list[dict]:
        """
        Parse the current page HTML and return a list of candidate link dicts:
            {"title": str, "url": str, "context": str}

        Filters out navigation/footer links, keeping only links that look like
        content (absolute URLs, non-trivial anchor text, not on skip-list domains).
        """
        html = page.content()
        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception:
            # lxml not installed — fall back to stdlib parser. Slower but always works.
            soup = BeautifulSoup(html, "html.parser")

        # Remove boilerplate sections
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        candidates = []
        seen_urls = set()

        for a in soup.find_all("a", href=True):
            href = str(a["href"]).strip()
            if not href.startswith("http"):
                continue

            # Skip internal navigation and known skip-list domains
            parsed = urllib.parse.urlparse(href)
            domain = parsed.netloc.lstrip("www.")
            if any(domain.endswith(skip) for skip in _SKIP_DOMAINS):
                continue

            anchor_text = a.get_text(separator=" ", strip=True)
            if len(anchor_text) < 5:
                continue  # skip icon-only / empty links

            if href in seen_urls:
                continue
            seen_urls.add(href)

            # Grab a short context snippet from the surrounding paragraph/div
            parent = a.find_parent(["p", "div", "li", "td"])
            context = parent.get_text(separator=" ", strip=True)[:200] if parent else ""

            candidates.append({"title": anchor_text[:120], "url": href, "context": context})

            if len(candidates) >= 40:  # cap to avoid overwhelming the LLM
                break

        return candidates

    def _rank_links_with_llm(
        self, query: str, candidates: list[dict], top_k: int
    ) -> list[str]:
        """
        Ask the LLM to pick the most relevant URLs from the candidate list.
        Returns up to top_k URLs in order of relevance.
        """
        numbered = "\n".join(
            f"{i + 1}. [{c['title']}] {c['url']}\n   Context: {c['context']}"
            for i, c in enumerate(candidates)
        )
        prompt = f"""You are helping locate the most relevant source for a research claim or query.

Query / claim: {query}

Links found on the search results page:
{numbered}

Select up to {top_k} links that are most likely to contain the full text or underlying data needed to verify this claim. Prefer direct download links (PDF, CSV, dataset files) over landing pages when both are present.

Return JSON:
{{
  "selected_indices": [1, 3, ...],  // 1-based indices, most relevant first
  "reasoning": "brief explanation"
}}
If none are relevant, return {{"selected_indices": [], "reasoning": "..."}}
"""
        try:
            result = self.llm_client.call_llm(
                prompt,
                response_format="json",
                task_name="browser_link_ranking",
                system_message="You are a research assistant selecting the most relevant sources.",
            )
            indices = result.get("selected_indices", [])
            urls = []
            for idx in indices:
                if isinstance(idx, int) and 1 <= idx <= len(candidates):
                    urls.append(candidates[idx - 1]["url"])
            return urls[:top_k]
        except Exception as e:
            logger.warning(f"  LLM link ranking failed: {e}; returning first {top_k} candidates")
            return [c["url"] for c in candidates[:top_k]]
