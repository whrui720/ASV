"""Text Downloader - Download text sources (PDF, HTML, plain text)"""

import logging
import requests
from pathlib import Path
from typing import Dict, Any
from .config import DOWNLOAD_TIMEOUT, TEXT_OUTPUT_DIR

logger = logging.getLogger(__name__)


class TextDownloader:
    """Download text sources (PDF, HTML, plain text)"""
    
    def __init__(self, output_dir: str = TEXT_OUTPUT_DIR):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
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
