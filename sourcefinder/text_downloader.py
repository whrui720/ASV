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
    
    def download(self, url: str, citation_id: str) -> Dict[str, Any]:
        """
        Download text source from URL.
        Returns: {downloaded: bool, format: str, path: str, text_content: str, error: str}
        """
        result = {
            'downloaded': False,
            'format': None,
            'path': None,
            'text_content': None,
            'error': None
        }
        
        try:
            logger.info(f"Downloading text from: {url}")
            response = self.session.get(url, timeout=DOWNLOAD_TIMEOUT)
            response.raise_for_status()
            
            # Detect format
            content_type = response.headers.get('content-type', '').lower()
            file_format = self._detect_format(url, content_type)
            
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
            
            result['downloaded'] = True
            result['format'] = file_format
            result['path'] = str(local_path)
            result['text_content'] = text_content
            logger.info(f"✓ Downloaded to: {local_path}")
            
        except Exception as e:
            result['error'] = str(e)
            logger.error(f"✗ Download failed: {e}")
        
        return result
    
    def _detect_format(self, url: str, content_type: str) -> str:
        """Detect file format"""
        url_lower = url.lower()
        
        if '.pdf' in url_lower or 'application/pdf' in content_type:
            return 'pdf'
        elif '.html' in url_lower or '.htm' in url_lower or 'text/html' in content_type:
            return 'html'
        
        return 'txt'
    
    def _extract_pdf_text(self, pdf_path: Path) -> str:
        """Extract text from PDF"""
        try:
            from PyPDF2 import PdfReader
            reader = PdfReader(str(pdf_path))
            text = '\n\n'.join([page.extract_text() for page in reader.pages])
            return text
        except Exception as e:
            logger.error(f"PDF extraction failed: {e}")
            return ""
    
    def _extract_html_text(self, html_content: str) -> str:
        """Extract text from HTML"""
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html_content, 'html.parser')
            # Remove script and style elements
            for script in soup(["script", "style"]):
                script.decompose()
            text = soup.get_text()
            # Clean up whitespace
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            text = '\n'.join(chunk for chunk in chunks if chunk)
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
        """
        # 1. Direct URL already known
        if citation_details and citation_details.url:
            logger.info(f"Downloading from known URL: {citation_details.url}")
            direct = self.download(citation_details.url, citation_id)
            if direct['downloaded']:
                return direct
            logger.info("  Direct URL failed; falling back to open-access resolution.")

        # 2. Try open-access resolution — iterate over ranked candidates.
        logger.info(f"Resolving citation [{citation_id}]: {raw_citation_text[:80]}...")
        candidates = self._paper_finder.find_urls(raw_citation_text)
        last_error: Optional[str] = None
        for i, url in enumerate(candidates, 1):
            logger.info(f"  Attempt {i}/{len(candidates)}: {url}")
            result = self.download(url, citation_id)
            if result['downloaded']:
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
                    return {
                        'downloaded': True,
                        'format': 'html',
                        'path': str(local_path),
                        'text_content': text_content,
                        'error': None,
                    }

        err = last_error or 'No URL found via open-access APIs or institutional cookies'
        return {'downloaded': False, 'format': None, 'path': None, 'text_content': None,
                'error': err}

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
