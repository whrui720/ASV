"""Text Downloader - Download text sources (PDF, HTML, plain text)"""

import logging
import requests
from pathlib import Path
from typing import Dict, Any, Optional
from .config import DOWNLOAD_TIMEOUT, TEXT_OUTPUT_DIR, INSTITUTIONAL_COOKIES
from .academic_paper_finder import AcademicPaperFinder
from run_paths import RunPaths

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

    def download(self, url: str, citation_id: str) -> Dict[str, Any]:
        """
        Download text source from URL.
        Returns: {downloaded: bool, format: str, path: str, text_content: str, error: str}

        A successful HTTP fetch is not enough. If the payload's extracted text is
        empty or under ``_MIN_USABLE_TEXT_CHARS``, we consider the download a
        failure (delete the on-disk file, return ``downloaded=False``) so the
        caller's cascade can try another URL.
        """
        result = {
            'downloaded': False,
            'format': None,
            'path': None,
            'text_content': None,
            'error': None
        }

        local_path: Optional[Path] = None
        try:
            logger.info(f"Downloading text from: {url}")
            response = self.session.get(url, timeout=DOWNLOAD_TIMEOUT)
            response.raise_for_status()

            # Detect format — magic-byte sniff dominates URL / content-type
            # hints, because publishers often serve HTML login walls at ``.pdf``
            # URLs and we don't want to feed HTML bytes to a PDF parser (or
            # vice-versa).
            content_type = response.headers.get('content-type', '').lower()
            file_format = self._detect_format(url, content_type, response.content[:512])

            # Save file
            filename = f"citation_{citation_id}_text.{file_format}"
            local_path = self.output_dir / filename

            # Save raw content
            with open(local_path, 'wb') as f:
                f.write(response.content)

            # Extract text based on format
            if file_format == 'pdf':
                text_content = self._extract_pdf_text(local_path)
            elif file_format in ['html', 'htm']:
                text_content = self._extract_html_text(response.text)
            else:
                text_content = response.text

            # Gate: require meaningful extracted content. Otherwise the RAG step
            # downstream sees nothing and the batch silently degrades to LLM
            # plausibility — worse than trying another candidate.
            usable_len = len((text_content or "").strip())
            if usable_len < self._MIN_USABLE_TEXT_CHARS:
                try:
                    local_path.unlink()
                except Exception:
                    pass
                err = (
                    f"Extraction produced {usable_len} usable chars "
                    f"(<{self._MIN_USABLE_TEXT_CHARS}); format={file_format}"
                )
                result['error'] = err
                logger.warning(f"  ✗ {err}")
                return result

            result['downloaded'] = True
            result['format'] = file_format
            result['path'] = str(local_path)
            result['text_content'] = text_content
            logger.info(f"✓ Downloaded to: {local_path} ({usable_len} chars extracted)")

        except Exception as e:
            # If we saved a file before the failure, clean it up.
            if local_path is not None:
                try:
                    local_path.unlink(missing_ok=True)  # type: ignore[arg-type]
                except Exception:
                    pass
            result['error'] = str(e)
            logger.error(f"✗ Download failed: {e}")

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

    def _extract_pdf_text(self, pdf_path: Path) -> str:
        """
        Extract text from PDF using a fallback chain of parsers.

        Order (best-quality first, most-tolerant last):
          1. pymupdf (fitz)  — fastest, best text quality, handles most malformed PDFs
          2. pdfminer.six    — battle-tested, better for column-heavy layouts
          3. pypdf           — modern successor to PyPDF2 (kept as last resort)

        A parser is considered successful only when it yields non-whitespace text.
        Returns "" when all three fail — download() then treats this as a
        failed extraction and the caller can iterate to the next candidate URL.
        """
        path_str = str(pdf_path)

        # 1. PyMuPDF (fitz) — primary.
        try:
            import fitz  # PyMuPDF
            with fitz.open(path_str) as doc:
                pages = [page.get_text() for page in doc]
            text = "\n\n".join(pages)
            if text.strip():
                logger.debug(f"  PDF extracted via pymupdf: {len(text)} chars")
                return text
            logger.debug("  pymupdf returned empty text — trying pdfminer.six")
        except Exception as e:
            logger.debug(f"  pymupdf extraction failed: {e}")

        # 2. pdfminer.six — fallback.
        try:
            from pdfminer.high_level import extract_text as pdfminer_extract
            text = pdfminer_extract(path_str) or ""
            if text.strip():
                logger.info(f"  PDF extracted via pdfminer.six (fallback): {len(text)} chars")
                return text
            logger.debug("  pdfminer.six returned empty text — trying pypdf")
        except Exception as e:
            logger.debug(f"  pdfminer.six extraction failed: {e}")

        # 3. pypdf — last resort.
        try:
            from pypdf import PdfReader
            reader = PdfReader(path_str)
            pages = [(p.extract_text() or "") for p in reader.pages]
            text = "\n\n".join(pages)
            if text.strip():
                logger.info(f"  PDF extracted via pypdf (fallback): {len(text)} chars")
                return text
        except Exception as e:
            logger.debug(f"  pypdf extraction failed: {e}")

        logger.warning(f"  All PDF extractors returned empty text for {pdf_path.name}")
        return ""

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

        The returned dict includes an ``attempts`` list — one entry per URL tried,
        tagged with the resolution phase (``direct`` / ``open_access`` /
        ``institutional_cookies``) — so callers can persist the full cascade.
        """
        attempts: list[dict] = []

        def _record(url: str, source: str, result: Dict[str, Any]) -> None:
            attempts.append({
                'url': url,
                'source': source,
                'downloaded': bool(result.get('downloaded')),
                'error': result.get('error'),
            })

        # 1. Direct URL already known
        if citation_details and citation_details.url:
            logger.info(f"Downloading from known URL: {citation_details.url}")
            direct = self.download(citation_details.url, citation_id)
            _record(citation_details.url, 'direct', direct)
            if direct['downloaded']:
                direct['attempts'] = attempts
                direct['winning_url'] = citation_details.url
                return direct
            logger.info("  Direct URL failed; falling back to open-access resolution.")

        # 2. Try open-access resolution — iterate over ranked candidates.
        logger.info(f"Resolving citation [{citation_id}]: {raw_citation_text[:80]}...")
        candidates = self._paper_finder.find_urls(raw_citation_text)
        last_error: Optional[str] = None
        for i, url in enumerate(candidates, 1):
            logger.info(f"  Attempt {i}/{len(candidates)}: {url}")
            result = self.download(url, citation_id)
            _record(url, 'open_access', result)
            if result['downloaded']:
                result['attempts'] = attempts
                result['winning_url'] = url
                return result
            last_error = result.get('error')

        # 3. Institutional cookie fallback — try CrossRef landing page URL if we have it
        if INSTITUTIONAL_COOKIES:
            doi_match = __import__('re').search(
                r'\b(10\.\d{4,}/\S+?)(?:[,\s\])}]|$)', raw_citation_text
            )
            if doi_match:
                landing = f"https://doi.org/{doi_match.group(1).rstrip('.')}"
                logger.info(f"Trying institutional cookies on landing page: {landing}")
                content = self._paper_finder.fetch_with_cookies(landing)
                if content:
                    filename = f"citation_{citation_id}_text.html"
                    local_path = self.output_dir / filename
                    local_path.write_bytes(content)
                    text_content = self._extract_html_text(content.decode("utf-8", errors="replace"))
                    attempts.append({
                        'url': landing,
                        'source': 'institutional_cookies',
                        'downloaded': True,
                        'error': None,
                    })
                    return {
                        'downloaded': True,
                        'format': 'html',
                        'path': str(local_path),
                        'text_content': text_content,
                        'error': None,
                        'attempts': attempts,
                        'winning_url': landing,
                    }
                attempts.append({
                    'url': landing,
                    'source': 'institutional_cookies',
                    'downloaded': False,
                    'error': 'fetch_with_cookies returned empty content',
                })

        err = last_error or 'No URL found via open-access APIs or institutional cookies'
        return {
            'downloaded': False, 'format': None, 'path': None, 'text_content': None,
            'error': err, 'attempts': attempts, 'winning_url': None,
        }

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
