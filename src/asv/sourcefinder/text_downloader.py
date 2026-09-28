"""Text Downloader - Download text sources (PDF, HTML, plain text)"""

import logging
import re
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from urllib.parse import urlparse

from .config import (
    DOWNLOAD_TIMEOUT,
    EZPROXY_HOST,
    EZPROXY_MAX_PER_RUN,
    TEXT_OUTPUT_DIR,
    INSTITUTIONAL_COOKIES,
    MAX_CANDIDATES_PER_BATCH,
)
from .academic_paper_finder import AcademicPaperFinder
from .content_quality import assess_content
from .polite_http import PoliteSession
from asv.core import credentials as creds
from asv.core.run_paths import RunPaths
from asv.core.verdicts import ContentQuality, content_quality_rank

logger = logging.getLogger(__name__)


def ezproxy_url(url: str, proxy_host: Optional[str] = None) -> Optional[str]:
    """Rewrite *url* through an EZproxy host — SOURCE_ACQUISITION.md §7.

    EZproxy access is a hostname rewrite, not a cookie hack::

        https://www.sciencedirect.com/science/article/pii/X
        -> https://www-sciencedirect-com.proxy.lib.umich.edu/science/article/pii/X

    Returns None when no proxy is configured, or when rewriting would be
    pointless: an open-access aggregator is not behind the library's
    subscription, and proxying it only spends the run's proxy budget.

    ``proxy_host=None`` means "use the configured default"; an explicit ``""``
    means "no proxy" and is honoured as such, so a caller can disable the
    rewrite without depending on the ambient environment.
    """
    proxy_host = (EZPROXY_HOST if proxy_host is None else proxy_host).strip().strip("/")
    if not proxy_host:
        return None
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    if not host or not parsed.scheme.startswith("http"):
        return None
    if host.endswith(proxy_host):
        return None  # already proxied
    from .fulltext_apis import _is_repository
    if _is_repository(url) or host in ("doi.org", "dx.doi.org"):
        return None
    proxied = host.replace(".", "-").replace(":", "-") + "." + proxy_host
    return parsed._replace(scheme="https", netloc=proxied).geturl()


class TextDownloader:
    """Download text sources (PDF, HTML, plain text)"""

    def __init__(
        self,
        run_paths: Optional[RunPaths] = None,
        output_dir: Optional[str] = None,
        llm_client=None,
    ):
        if run_paths is not None:
            self.output_dir = run_paths.text_sources
        elif output_dir is not None:
            self.output_dir = Path(output_dir)
            self.output_dir.mkdir(parents=True, exist_ok=True)
        else:
            self.output_dir = Path(TEXT_OUTPUT_DIR)
            self.output_dir.mkdir(parents=True, exist_ok=True)
        # A browser-shaped UA was never enough on its own: 80% of failed fetches
        # were 403s from publishers that also look at Referer, Sec-Fetch-* and
        # request cadence. PoliteSession supplies all three (F2, F7).
        self.session = PoliteSession(default_headers={
            'Accept': (
                'text/html,application/xhtml+xml,application/xml;q=0.9,'
                'application/pdf;q=0.9,*/*;q=0.8'
            ),
            'Accept-Language': 'en-US,en;q=0.9',
        })
        self._paper_finder = AcademicPaperFinder(llm_client=llm_client)
        #: Proxied fetches used so far. Bulk downloading through a library proxy
        #: is what gets institutional access suspended, so the budget is per-run
        #: and shared across every batch.
        self._ezproxy_used = 0
    
    # Minimum extracted text length (non-whitespace) required to treat a fetched
    # PDF/HTML as a usable source. Anything smaller is almost certainly a
    # login-wall, an error page, or a corrupted PDF that all extractors bailed
    # on — flagging as a failed download lets download_with_resolution iterate
    # to the next candidate URL instead of feeding empty text to the RAG step.
    _MIN_USABLE_TEXT_CHARS = 200

    def download(
        self, url: str, citation_id: str, *, filename_suffix: str = ""
    ) -> Dict[str, Any]:
        """
        Download text source from URL via ``self.session`` (a ``requests.Session``).
        Returns: {downloaded, format, path, text_content, content_quality,
                  content_signals, judgeable, error}

        A successful HTTP fetch is not enough, on two levels. If extraction
        yields less than ``_MIN_USABLE_TEXT_CHARS`` the payload is rejected
        outright (file deleted, ``downloaded=False``) so the caller's cascade
        continues. If it yields *plenty* of text that is nonetheless an abstract
        or an access wall, ``downloaded`` stays True — we really did fetch
        something and the manifest should say so — but ``judgeable`` is False
        and the orchestrator refuses to judge against it (Tier 0.3).
        """
        try:
            logger.info(f"Downloading text from: {url}")
            # Per-host auth headers (Wiley TDM token, Elsevier API key) are keyed
            # on the host rather than attached to whichever resolver produced the
            # URL, so a TDM link carries its token however it was found.
            response = self.session.get(
                url,
                timeout=DOWNLOAD_TIMEOUT,
                browser_headers=True,
                headers=creds.auth_headers_for(url) or None,
            )
            response.raise_for_status()
        except Exception as e:
            logger.error(f"✗ Download failed: {e}")
            return {
                'downloaded': False, 'format': None, 'path': None,
                'text_content': None, 'content_quality': None,
                'content_signals': None, 'judgeable': False, 'error': str(e),
            }

        content_type = response.headers.get('content-type', '').lower()
        return self._process_bytes(
            response.content, url, citation_id, content_type,
            filename_suffix=filename_suffix,
        )

    def _process_bytes(
        self,
        body: bytes,
        url: str,
        citation_id: str,
        content_type: str = "",
        *,
        filename_suffix: str = "",
    ) -> Dict[str, Any]:
        """
        Save raw bytes, sniff format, extract text, and classify the result.
        Shared between the ``requests``-based ``download()`` path and the
        Playwright browser fallback in ``download_with_resolution()`` — both
        hand off raw bytes here so format detection, on-disk layout, and the
        content-quality gate stay consistent. This is the single choke point
        Tier 0.3 hangs off.
        """
        result = {
            'downloaded': False,
            'format': None,
            'path': None,
            'text_content': None,
            'content_quality': None,
            'content_signals': None,
            'judgeable': False,
            'error': None,
        }

        local_path: Optional[Path] = None
        try:
            # Detect format — magic-byte sniff dominates URL / content-type
            # hints, because publishers often serve HTML login walls at ``.pdf``
            # URLs and we don't want to feed HTML bytes to a PDF parser (or
            # vice-versa).
            file_format = self._detect_format(url, content_type, body[:512])

            filename = f"citation_{citation_id}{filename_suffix}_text.{file_format}"
            local_path = self.output_dir / filename
            with open(local_path, 'wb') as f:
                f.write(body)

            page_count: Optional[int] = None
            if file_format == 'pdf':
                text_content, page_count = self._extract_pdf_text(local_path)
            elif file_format == 'xml':
                text_content = self._extract_xml_text(body.decode('utf-8', errors='replace'))
            elif file_format in ('html', 'htm'):
                text_content = self._extract_html_text(body.decode('utf-8', errors='replace'))
            else:
                text_content = body.decode('utf-8', errors='replace')

            assessment = assess_content(
                text_content, file_format=file_format, page_count=page_count, url=url,
            )
            result['content_quality'] = assessment.quality
            result['content_signals'] = assessment.signals

            # REJECTED keeps the pre-Tier-0 behaviour exactly: delete the file
            # and report a failed download, so the cascade moves on. Everything
            # else is kept — an abstract is a real fetch, it is just not
            # evidence, and the distinction has to survive into the manifest.
            if assessment.quality == ContentQuality.REJECTED:
                try:
                    local_path.unlink()
                except Exception:
                    pass
                result['error'] = f"Unusable content: {assessment.reason}"
                logger.warning(f"  ✗ {result['error']}")
                return result

            result['downloaded'] = True
            result['format'] = file_format
            result['path'] = str(local_path)
            result['text_content'] = text_content
            result['judgeable'] = assessment.judgeable
            usable_len = assessment.signals.get('usable_chars', 0)
            if assessment.judgeable:
                logger.info(
                    f"✓ Downloaded to: {local_path} "
                    f"({usable_len} chars, full text — {assessment.reason})"
                )
            else:
                logger.warning(
                    f"  ⚠ Fetched but not judgeable [{assessment.quality.value}]: "
                    f"{assessment.reason}"
                )

        except Exception as e:
            if local_path is not None:
                try:
                    local_path.unlink(missing_ok=True)  # type: ignore[arg-type]
                except Exception:
                    pass
            result['error'] = str(e)
            logger.error(f"✗ Processing failed: {e}")

        return result

    def _detect_format(
        self, url: str, content_type: str, content_head: bytes = b""
    ) -> str:
        """
        Detect payload format.

        Priority (most reliable first):
          1. Magic bytes — trustworthy regardless of what the URL claims
          2. Content-Type header — set by the actual server
          3. URL extension — cheap hint, but often lies (e.g. ``.pdf`` URLs that
             redirect to a login-wall HTML page)
        """
        head_stripped = content_head.lstrip()
        head_lower = head_stripped[:256].lower()

        # 1. Magic-byte sniff
        if content_head.startswith(b"%PDF-"):
            return 'pdf'
        if head_lower.startswith(b"<!doctype html") or head_lower.startswith(b"<html"):
            return 'html'
        # JATS full text from Europe PMC / NCBI efetch / Springer arrives as XML
        # and must not reach the HTML extractor, which would keep the markup's
        # metadata soup and drop the article body's structure.
        if head_lower.startswith(b"<?xml") or head_lower.startswith(b"<!doctype article") \
                or head_lower.startswith(b"<article") or head_lower.startswith(b"<pmc-articleset"):
            return 'xml'

        # 2. Content-Type header
        if 'application/pdf' in content_type:
            return 'pdf'
        if 'xml' in content_type:
            return 'xml'
        if 'text/html' in content_type:
            return 'html'

        # 3. URL extension
        url_lower = url.lower()
        if '.pdf' in url_lower:
            return 'pdf'
        if '.xml' in url_lower or 'fulltextxml' in url_lower:
            return 'xml'
        if '.html' in url_lower or '.htm' in url_lower:
            return 'html'

        return 'txt'

    def _extract_xml_text(self, xml_content: str) -> str:
        """Extract readable article text from JATS / PMC XML.

        This is the payoff of adding Europe PMC and the PMC deposits: the
        publisher's own structured full text, with no PDF layout to reconstruct
        and no landing-page chrome to strip. Section titles are emitted on their
        own lines because the content-quality classifier keys off IMRaD headings
        — losing them would make real full text look like an abstract.

        ``<ref-list>`` is dropped: a bibliography is the single biggest source of
        false TF-IDF matches, and the classifier separately penalises pages that
        are mostly references.
        """
        try:
            from bs4 import BeautifulSoup
            try:
                soup = BeautifulSoup(xml_content, "lxml-xml")
            except Exception:
                soup = BeautifulSoup(xml_content, "html.parser")

            for tag in soup.find_all(["ref-list", "back", "journal-meta",
                                      "author-notes", "fn-group", "table-wrap-foot"]):
                tag.decompose()

            parts: List[str] = []
            title = soup.find("article-title")
            if title:
                parts.append(title.get_text(" ", strip=True))

            abstract = soup.find("abstract")
            if abstract:
                parts.append("Abstract")
                parts.append(abstract.get_text(" ", strip=True))

            body = soup.find("body")
            scope = body if body is not None else soup
            for section in scope.find_all("sec", recursive=True):
                sec_title = section.find("title", recursive=False)
                if sec_title:
                    heading = sec_title.get_text(" ", strip=True)
                    if heading:
                        parts.append("\n" + heading)
                for para in section.find_all(["p", "list-item"], recursive=False):
                    text = para.get_text(" ", strip=True)
                    if text:
                        parts.append(text)

            # Some deposits carry body paragraphs with no <sec> wrapper at all.
            if body is not None and not body.find("sec"):
                for para in body.find_all("p"):
                    text = para.get_text(" ", strip=True)
                    if text:
                        parts.append(text)

            out = "\n".join(p for p in parts if p and p.strip())
            if out.strip():
                logger.debug(f"  XML extracted via JATS parse: {len(out)} chars")
                return out

            # Not JATS after all (an error document, an OAI wrapper). Fall back
            # to every text node rather than reporting an empty extraction.
            return soup.get_text("\n", strip=True)
        except Exception as e:
            logger.error(f"XML extraction failed: {e}")
            return xml_content

    def _extract_pdf_text(self, pdf_path: Path) -> Tuple[str, Optional[int]]:
        """
        Extract text from PDF using a fallback chain of parsers.

        Order (best-quality first, most-tolerant last):
          1. pymupdf (fitz)  — fastest, best text quality, handles most malformed PDFs
          2. pdfminer.six    — battle-tested, better for column-heavy layouts
          3. pypdf           — modern successor to PyPDF2 (kept as last resort)

        A parser is considered successful only when it yields non-whitespace text.
        Returns ``("", page_count)`` when all three fail — download() then treats
        this as a failed extraction and the caller can iterate to the next
        candidate URL.

        Also returns the page count (Tier 0.3): a one- or two-page PDF carrying
        an "Abstract" heading is an abstract, not an article, and page count is
        the cheapest way to know that. It was previously computed and discarded.
        """
        path_str = str(pdf_path)
        page_count: Optional[int] = None

        # 1. PyMuPDF (fitz) — primary.
        try:
            import fitz  # PyMuPDF
            with fitz.open(path_str) as doc:
                page_count = doc.page_count
                pages = [page.get_text() for page in doc]  # type: ignore[attr-defined]
            text = "\n\n".join(pages)
            if text.strip():
                logger.debug(f"  PDF extracted via pymupdf: {len(text)} chars, {page_count}p")
                return text, page_count
            logger.debug("  pymupdf returned empty text — trying pdfminer.six")
        except Exception as e:
            logger.debug(f"  pymupdf extraction failed: {e}")

        # 2. pdfminer.six — fallback.
        try:
            from pdfminer.high_level import extract_text as pdfminer_extract
            text = pdfminer_extract(path_str) or ""
            if text.strip():
                logger.info(f"  PDF extracted via pdfminer.six (fallback): {len(text)} chars")
                return text, page_count
            logger.debug("  pdfminer.six returned empty text — trying pypdf")
        except Exception as e:
            logger.debug(f"  pdfminer.six extraction failed: {e}")

        # 3. pypdf — last resort.
        try:
            from pypdf import PdfReader
            reader = PdfReader(path_str)
            if page_count is None:
                page_count = len(reader.pages)
            pages = [(p.extract_text() or "") for p in reader.pages]
            text = "\n\n".join(pages)
            if text.strip():
                logger.info(f"  PDF extracted via pypdf (fallback): {len(text)} chars")
                return text, page_count
        except Exception as e:
            logger.debug(f"  pypdf extraction failed: {e}")

        logger.warning(f"  All PDF extractors returned empty text for {pdf_path.name}")
        return "", page_count

    def _extract_html_text(self, html_content: str) -> str:
        """
        Extract text from HTML.

        Publisher pages (Nature, Springer, etc.) wrap the actual article body in
        a lot of navigation chrome — "Skip to main content", cookie banners, sign-in
        prompts, related-article rails. Feeding all of that to RAG dilutes TF-IDF
        similarity and lets nav phrases outrank real content.

        Strategy:
          1. Strip obvious non-content elements (script, style, nav, header, footer,
             aside, form, button, and elements with common junk classes/ids).
          2. Look for a semantic article container (``<article>``, ``<main>``,
             ``[role="main"]``, or common publisher-specific selectors).
          3. If found, extract text only from that container. Otherwise fall back
             to whole-document text.
        """
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html_content, 'html.parser')

            # 1. Kill elements that are never article text, by tag. Safe to do
            #    document-wide.
            for tag in soup(["script", "style", "nav", "header", "footer",
                             "aside", "form", "button", "noscript", "iframe"]):
                tag.decompose()

            # 2. Pick the content root *first*, then clean inside it.
            #
            #    Order matters, and getting it wrong cost us a whole publisher.
            #    Cleaning first meant a junk-class match anywhere in the tree
            #    could delete an *ancestor* of the article: nature.com wraps its
            #    content in <div id="content" class="… eds-l-with-sidebar">, the
            #    substring "sidebar" matched, and 284KB of successfully fetched
            #    article became zero characters of extracted text — reported as
            #    a failed download. Scoping the cleanup to the content root
            #    makes an ancestor's layout class structurally unable to matter.
            container = (
                soup.find("article")
                or soup.find("main")
                or soup.find(attrs={"role": "main"})
                or soup.find(class_="c-article-body")
                or soup.find(class_="article-body")
                or soup.find(class_="article__body")
                or soup.find(id="article-body")
                or soup.find(id="main-content")
                or soup.find(id="content")
                or soup.body
                or soup
            )

            full_text = container.get_text(separator="\n")

            # 3. Strip navigation chrome from *within* the chosen root: cookie
            #    banners, related-article rails, sign-in blocks. These dilute
            #    TF-IDF and let nav phrases outrank real content.
            junk_patterns = ("cookie", "banner", "signin", "sign-in", "login",
                             "related", "sidebar", "advert", "promo", "footer",
                             "header", "nav", "skip-link", "menu", "share",
                             "citation-tools", "metrics", "altmetric")
            # No single element that holds most of the root's text is chrome.
            # This is the backstop for the failure above: even a selector we
            # have not seen cannot delete the article.
            keep_threshold = max(200, int(len(full_text) * 0.4))

            def _attrs_of(el) -> str:
                c = el.get("class")
                classes = (" ".join(c) if isinstance(c, list) else str(c or ""))
                return (classes + " " + str(el.get("id") or "")).lower()

            # Snapshot first — decompose() detaches descendants, and iterating a
            # live tree would then walk into freed nodes.
            for el in list(container.find_all(attrs={"class": True})) + \
                    list(container.find_all(attrs={"id": True})):
                if el is None or el.parent is None or el is container:
                    continue
                if not any(p in _attrs_of(el) for p in junk_patterns):
                    continue
                if len(el.get_text(separator=" ")) > keep_threshold:
                    continue
                el.decompose()

            text = container.get_text(separator="\n")

            # 4. Whitespace cleanup.
            def _tidy(raw: str) -> str:
                lines = (line.strip() for line in raw.splitlines())
                chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
                return "\n".join(chunk for chunk in chunks if chunk)

            cleaned = _tidy(text)
            # 5. Last-resort guard: if cleaning destroyed the page rather than
            #    tidying it, keep what we had. A noisy document is recoverable;
            #    an empty one is reported as a failed fetch.
            if len(cleaned) < min(200, len(_tidy(full_text))):
                logger.warning(
                    "  HTML cleanup removed almost everything "
                    f"({len(cleaned)} of {len(full_text)} chars) — keeping the "
                    "uncleaned article body instead"
                )
                return _tidy(full_text)
            return cleaned
        except Exception as e:
            logger.error(f"HTML extraction failed: {e}")
            return html_content
    
    def download_with_resolution(
        self,
        citation_details,           # CitationDetails | None
        citation_id: str,
        raw_citation_text: str,     # full bibliography entry text
    ) -> Dict[str, Any]:
        """
        Resolve a citation to a URL then download it.

        Resolution order:
          1. Use citation_details.url directly if already populated
          2. Use AcademicPaperFinder — iterates candidate URLs, tries each on 4xx failure
          3. Use institutional cookies on the landing page if configured
          4. Retry previously-attempted URLs via Playwright browser (uses the
             human-login session harvested at pipeline startup)

        The returned dict includes an ``attempts`` list — one entry per URL tried,
        tagged with the resolution phase (``direct`` / ``open_access`` /
        ``institutional_cookies`` / ``browser``) and with the content quality of
        whatever came back — so callers can persist the full cascade.

        **Best-of-N, not first-success (Tier 0.3, TIER0_PLAN.md §4.4).** This
        used to return on the first candidate that fetched. With the content
        gate in place that would be strictly harmful: candidate 1 is typically a
        publisher landing page, which fetches fine, gets refused as
        ``abstract_only``, and the Europe PMC full-text mirror sitting at
        candidate 2 is never tried — converting a fake pass into an abstention
        while leaving real evidence on the table. So we walk the candidate list
        keeping the *best* result, and stop early the moment full text appears.
        """
        attempts: list[dict] = []
        best: Optional[Dict[str, Any]] = None
        best_url: Optional[str] = None
        last_error: Optional[str] = None
        fetches = 0

        def _discard(result: Optional[Dict[str, Any]]) -> None:
            """Delete a superseded candidate's file so the run folder only ever
            holds the winner (keeps post-batch cleanup and the manifest honest)."""
            path = (result or {}).get('path')
            if not path:
                return
            try:
                Path(path).unlink(missing_ok=True)  # type: ignore[arg-type]
            except Exception:
                pass

        def _consider(url: str, source: str, result: Dict[str, Any]) -> bool:
            """Record the attempt and keep it if it beats what we have.

            Returns True when the result is full text, i.e. nothing can beat it
            and the caller should stop."""
            nonlocal best, best_url, last_error
            attempts.append({
                'url': url,
                'source': source,
                'downloaded': bool(result.get('downloaded')),
                'content_quality': result.get('content_quality'),
                'error': result.get('error'),
            })
            if not result.get('downloaded'):
                last_error = result.get('error') or last_error
                return False
            better = best is None or (
                content_quality_rank(result.get('content_quality'))
                > content_quality_rank(best.get('content_quality'))
            )
            if better:
                _discard(best)
                best, best_url = result, url
            else:
                _discard(result)
            return bool(result.get('judgeable'))

        # 1. Direct URL already known
        if citation_details and citation_details.url:
            logger.info(f"Downloading from known URL: {citation_details.url}")
            fetches += 1
            if _consider(
                citation_details.url, 'direct',
                self.download(citation_details.url, citation_id, filename_suffix="_c1"),
            ):
                return self._finish(best, best_url, attempts)
            logger.info("  Direct URL was not full text; continuing resolution.")

        # 2. Open-access resolution — iterate over ranked candidates.
        #    Each attempt is tagged with the *resolver* that produced it
        #    (``europepmc_fulltext``, ``unpaywall``, ``openalex``, …) rather than
        #    a generic ``open_access``, so the manifest says which service is
        #    actually earning its place.
        logger.info(f"Resolving citation [{citation_id}]: {raw_citation_text[:80]}...")
        known_doi = getattr(citation_details, "doi", None) if citation_details else None
        candidates = self._paper_finder.find_candidates(
            raw_citation_text, known_doi=known_doi
        )
        tried_urls = {a['url'] for a in attempts}
        for candidate in candidates:
            if fetches >= MAX_CANDIDATES_PER_BATCH:
                logger.info(
                    f"  Candidate cap ({MAX_CANDIDATES_PER_BATCH}) reached; "
                    f"keeping best so far."
                )
                break
            if candidate.url in tried_urls:
                continue
            tried_urls.add(candidate.url)
            fetches += 1
            logger.info(f"  Attempt {fetches} [{candidate.kind}]: {candidate.url}")
            if _consider(
                candidate.url, candidate.source,
                self.download(candidate.url, citation_id, filename_suffix=f"_c{fetches}"),
            ):
                return self._finish(best, best_url, attempts)

        # 3. Institutional cookie fallback — try the DOI landing page if we have one.
        #    Only worth doing when we still lack full text.
        if INSTITUTIONAL_COOKIES:
            doi_match = re.search(
                r'\b(10\.\d{4,}/\S+?)(?:[,\s\])}]|$)', raw_citation_text
            )
            if doi_match:
                landing = f"https://doi.org/{doi_match.group(1).rstrip('.')}"
                logger.info(f"Trying institutional cookies on landing page: {landing}")
                content = self._paper_finder.fetch_with_cookies(landing)
                if content:
                    fetches += 1
                    result = self._process_bytes(
                        content, landing, citation_id,
                        filename_suffix=f"_c{fetches}",
                    )
                    if _consider(landing, 'institutional_cookies', result):
                        return self._finish(best, best_url, attempts)
                else:
                    attempts.append({
                        'url': landing,
                        'source': 'institutional_cookies',
                        'downloaded': False,
                        'content_quality': None,
                        'error': 'fetch_with_cookies returned empty content',
                    })

        # 4. Playwright browser fallback — retry previously-attempted URLs through
        # the authenticated browser context. Because the orchestrator opens
        # paywall domains for manual login before the pipeline starts and then
        # bridges those cookies into both requests sessions and the browser
        # context, ``download_url`` here fetches with the user's actual session.
        # Capped at 5 URLs to avoid runaway retries.
        browser_searcher = getattr(self._paper_finder, "browser_searcher", None)
        if browser_searcher is not None and attempts:
            seen: set[str] = set()
            browser_tries = 0
            for a in attempts[:]:  # snapshot — we append to attempts inside the loop
                u = a.get("url")
                if not u or u in seen:
                    continue
                seen.add(u)
                if browser_tries >= 5:
                    break
                browser_tries += 1
                logger.info(f"  Browser retry {browser_tries}: {u}")
                body = browser_searcher.download_url(u)
                if not body:
                    attempts.append({
                        'url': u,
                        'source': 'browser',
                        'downloaded': False,
                        'content_quality': None,
                        'error': 'browser fetch returned no content',
                    })
                    continue
                fetches += 1
                result = self._process_bytes(
                    body, u, citation_id, filename_suffix=f"_c{fetches}",
                )
                if _consider(u, 'browser', result):
                    return self._finish(best, best_url, attempts)

        # 5. EZproxy — the library's sanctioned access path (§7). A hostname
        # rewrite, fetched through the *browser* context so the user's SSO
        # session applies; ASV never sees a credential. Strictly better than
        # INSTITUTIONAL_COOKIES: it survives cookie rotation and asks nobody to
        # paste secrets into a .env.
        #
        # Guardrails matter more here than anywhere else in the pipeline —
        # bulk downloading through a proxy is what gets a university's access
        # suspended — so this is opt-in, capped per run, and only ever applied
        # to publisher hosts that already refused us.
        #
        # Reaching this point means no candidate produced judgeable full text —
        # ``_consider`` returns early when one does. So this runs for an
        # abstract-only batch too, not just a total failure: an abstract is
        # precisely the case a subscription can upgrade, and abstaining on one
        # we could have read is the recall cost Tier 0.3 pays and this repays.
        if EZPROXY_HOST and browser_searcher is not None:
            proxied_tries = 0
            for a in attempts[:]:
                if proxied_tries >= 3:
                    break
                if self._ezproxy_used >= EZPROXY_MAX_PER_RUN:
                    logger.warning(
                        f"  EZproxy budget for this run exhausted "
                        f"({EZPROXY_MAX_PER_RUN}) — not proxying further."
                    )
                    break
                if a.get('source') == 'ezproxy':
                    continue
                proxied = ezproxy_url(a.get('url') or "")
                if not proxied or proxied in tried_urls:
                    continue
                tried_urls.add(proxied)
                proxied_tries += 1
                self._ezproxy_used += 1
                logger.info(f"  EZproxy retry {proxied_tries}: {proxied}")
                body = browser_searcher.download_url(proxied)
                if not body:
                    attempts.append({
                        'url': proxied,
                        'source': 'ezproxy',
                        'downloaded': False,
                        'content_quality': None,
                        'error': 'proxied fetch returned no content (SSO session may be missing)',
                    })
                    continue
                fetches += 1
                if _consider(proxied, 'ezproxy', self._process_bytes(
                    body, proxied, citation_id, filename_suffix=f"_c{fetches}",
                )):
                    return self._finish(best, best_url, attempts)

        if best is not None:
            logger.warning(
                f"  Best available source for [{citation_id}] is "
                f"{best.get('content_quality')} — not full text."
            )
            return self._finish(best, best_url, attempts)

        err = last_error or 'No URL found via open-access APIs, institutional cookies, or browser'
        return {
            'downloaded': False, 'format': None, 'path': None, 'text_content': None,
            'content_quality': None, 'content_signals': None, 'judgeable': False,
            'error': err, 'attempts': attempts, 'winning_url': None,
        }

    @staticmethod
    def _finish(
        best: Optional[Dict[str, Any]],
        best_url: Optional[str],
        attempts: list[dict],
    ) -> Dict[str, Any]:
        """Attach the cascade to the winning result."""
        result = dict(best or {})
        result['attempts'] = attempts
        result['winning_url'] = best_url
        return result

    def delete_text(self, filename: str) -> Dict[str, Any]:
        """
        Delete a text file from the text_sources folder.
        
        Args:
            filename: Name of the file to delete (e.g., "citation_123_text.pdf")
        
        Returns: {deleted: bool, path: str, error: str}
        """
        result = {
            'deleted': False,
            'path': None,
            'error': None
        }
        
        try:
            file_path = self.output_dir / filename
            
            if not file_path.exists():
                result['error'] = f"File not found: {filename}"
                logger.warning(f"File not found: {file_path}")
                return result
            
            if not file_path.is_file():
                result['error'] = f"Not a file: {filename}"
                logger.warning(f"Not a file: {file_path}")
                return result
            
            file_path.unlink()
            result['deleted'] = True
            result['path'] = str(file_path)
            logger.info(f"✓ Deleted text file: {file_path}")
            
        except Exception as e:
            result['error'] = str(e)
            logger.error(f"✗ Delete failed: {e}")
        
        return result
