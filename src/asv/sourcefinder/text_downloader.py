"""Text Downloader - Download text sources (PDF, HTML, plain text)"""

import logging
import re
import requests
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
from .config import (
    DOWNLOAD_TIMEOUT,
    TEXT_OUTPUT_DIR,
    INSTITUTIONAL_COOKIES,
    MAX_CANDIDATES_PER_BATCH,
)
from .academic_paper_finder import AcademicPaperFinder
from .content_quality import assess_content
from asv.core.run_paths import RunPaths
from asv.core.verdicts import ContentQuality, content_quality_rank

logger = logging.getLogger(__name__)


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
        self.session = requests.Session()
        # Browser-like headers reduce trivial 403s from publishers that sniff UA.
        self.session.headers.update({
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/120.0.0.0 Safari/537.36'
            ),
            'Accept': 'application/pdf,text/html;q=0.9,application/xhtml+xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
        })
        self._paper_finder = AcademicPaperFinder(llm_client=llm_client)
    
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
            response = self.session.get(url, timeout=DOWNLOAD_TIMEOUT)
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

        # 2. Content-Type header
        if 'application/pdf' in content_type:
            return 'pdf'
        if 'text/html' in content_type:
            return 'html'

        # 3. URL extension
        url_lower = url.lower()
        if '.pdf' in url_lower:
            return 'pdf'
        if '.html' in url_lower or '.htm' in url_lower:
            return 'html'

        return 'txt'

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

            # 1. Kill non-content elements.
            for tag in soup(["script", "style", "nav", "header", "footer",
                             "aside", "form", "button", "noscript", "iframe"]):
                tag.decompose()

            # Kill common junk containers by class/id (banners, cookie prompts,
            # related-article rails, sign-in blocks). Snapshot first — decompose()
            # detaches descendants and iterating a live tree would then crash.
            junk_patterns = ("cookie", "banner", "signin", "sign-in", "login",
                             "related", "sidebar", "advert", "promo", "footer",
                             "header", "nav", "skip-link", "menu", "share",
                             "citation-tools", "metrics", "altmetric")

            def _classes_of(el):
                c = el.get("class")
                if not c:
                    return ""
                return " ".join(c).lower() if isinstance(c, list) else str(c).lower()

            junk_class_els = [
                el for el in list(soup.find_all(attrs={"class": True}))
                if el is not None and el.parent is not None
                and any(p in _classes_of(el) for p in junk_patterns)
            ]
            for el in junk_class_els:
                if el.parent is not None:
                    el.decompose()

            junk_id_els = [
                el for el in list(soup.find_all(attrs={"id": True}))
                if el is not None and el.parent is not None
                and any(p in str(el.get("id", "")).lower() for p in junk_patterns)
            ]
            for el in junk_id_els:
                if el.parent is not None:
                    el.decompose()

            # 2. Prefer a semantic article container.
            #    Common publisher selectors (Nature/Springer use ``.c-article-body``,
            #    ScienceDirect uses ``#body``, PMC uses ``.jig-ncbiinpagenav``…).
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

            text = container.get_text(separator="\n")

            # 3. Whitespace cleanup.
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            text = "\n".join(chunk for chunk in chunks if chunk)
            return text
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
        logger.info(f"Resolving citation [{citation_id}]: {raw_citation_text[:80]}...")
        known_doi = getattr(citation_details, "doi", None) if citation_details else None
        candidates = self._paper_finder.find_urls(raw_citation_text, known_doi=known_doi)
        tried_urls = {a['url'] for a in attempts}
        for url in candidates:
            if fetches >= MAX_CANDIDATES_PER_BATCH:
                logger.info(
                    f"  Candidate cap ({MAX_CANDIDATES_PER_BATCH}) reached; "
                    f"keeping best so far."
                )
                break
            if url in tried_urls:
                continue
            tried_urls.add(url)
            fetches += 1
            logger.info(f"  Attempt {fetches}: {url}")
            if _consider(
                url, 'open_access',
                self.download(url, citation_id, filename_suffix=f"_c{fetches}"),
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
