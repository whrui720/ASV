"""
Text Downloader - Download raw text for qualitative objective claims with citations

Downloads PDFs, web pages, and other text sources for qualitative claim validation.
"""

import requests
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from urllib.parse import urlparse
import PyPDF2
from io import BytesIO

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TextDownloader:
    """
    Downloads raw text from citation sources for qualitative claims.
    
    Supports:
    - PDF documents (academic papers, reports)
    - Web pages (news articles, blogs)
    - Plain text files
    """
    
    def __init__(self, output_dir: str = "./sources"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    def download_text_source(self, url: str, claim_id: str) -> Dict[str, Any]:
        """
        Download text source from URL.
        
        Args:
            url: URL to download from
            claim_id: Unique identifier for the claim
            
        Returns:
            Dict with download status and metadata:
            {
                'downloaded': bool,
                'data_format': str,  # 'pdf', 'html', 'txt'
                'platform': str,
                'source_url': str,
                'local_path': str,
                'text_content': str,  # Extracted text
                'error': str (if failed)
            }
        """
        result = {
            'downloaded': False,
            'data_format': None,
            'platform': 'text',
            'source_url': url,
            'local_path': None,
            'text_content': None,
            'error': None
        }
        
        try:
            logger.info(f"Downloading text from: {url}")
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            
            # Detect content type
            content_type = response.headers.get('content-type', '').lower()
            
            if 'pdf' in content_type or url.lower().endswith('.pdf'):
                result['data_format'] = 'pdf'
                text_content = self._extract_pdf_text(response.content)
                filename = f"claim_{claim_id}_source.pdf"
                
                # Save PDF
                local_path = self.output_dir / filename
                with open(local_path, 'wb') as f:
                    f.write(response.content)
                
            elif 'html' in content_type or 'text/html' in content_type:
                result['data_format'] = 'html'
                text_content = self._extract_html_text(response.text)
                filename = f"claim_{claim_id}_source.html"
                
                # Save HTML
                local_path = self.output_dir / filename
                with open(local_path, 'w', encoding='utf-8') as f:
                    f.write(response.text)
                
            else:
                result['data_format'] = 'txt'
                text_content = response.text
                filename = f"claim_{claim_id}_source.txt"
                
                # Save text
                local_path = self.output_dir / filename
                with open(local_path, 'w', encoding='utf-8') as f:
                    f.write(text_content)
            
            result['downloaded'] = True
            result['local_path'] = str(local_path)
            result['text_content'] = text_content
            logger.info(f"✓ Successfully downloaded text source to {local_path}")
            
        except requests.exceptions.RequestException as e:
            result['error'] = f"Network error: {str(e)}"
            logger.error(f"✗ Download failed: {str(e)}")
        except Exception as e:
            result['error'] = f"Unexpected error: {str(e)}"
            logger.error(f"✗ Unexpected error: {str(e)}")
        
        return result
    
    def download_from_citation(self, citation_details: Dict[str, Any], claim_id: str) -> Dict[str, Any]:
        """
        Download text source from citation details.
        
        Args:
            citation_details: Citation metadata (url, doi, title, etc.)
            claim_id: Unique identifier for the claim
            
        Returns:
            Download result dict
        """
        # Try URL first
        if citation_details.get('url'):
            return self.download_text_source(citation_details['url'], claim_id)
        
        # Try DOI
        if citation_details.get('doi'):
            doi_url = f"https://doi.org/{citation_details['doi']}"
            return self.download_text_source(doi_url, claim_id)
        
        # Try constructing Google Scholar search URL as fallback
        if citation_details.get('title'):
            # This won't download but provides a search URL
            title = citation_details['title']
            search_url = f"https://scholar.google.com/scholar?q={title.replace(' ', '+')}"
            
            return {
                'downloaded': False,
                'data_format': None,
                'platform': None,
                'source_url': search_url,
                'local_path': None,
                'text_content': None,
                'error': 'No direct URL found. Manual search required.'
            }
        
        return {
            'downloaded': False,
            'data_format': None,
            'platform': None,
            'source_url': None,
            'local_path': None,
            'text_content': None,
            'error': 'No URL or DOI found in citation details'
        }
    
    def _extract_pdf_text(self, pdf_content: bytes) -> str:
        """
        Extract text from PDF bytes.
        
        Returns extracted text as string.
        """
        try:
            pdf_file = BytesIO(pdf_content)
            pdf_reader = PyPDF2.PdfReader(pdf_file)
            
            text_parts = []
            for page in pdf_reader.pages:
                text_parts.append(page.extract_text())
            
            text = "\n".join(text_parts)
            logger.info(f"Extracted {len(text)} characters from PDF")
            return text
            
        except Exception as e:
            logger.error(f"PDF text extraction failed: {str(e)}")
            return ""
    
    def _extract_html_text(self, html_content: str) -> str:
        """
        Extract readable text from HTML.
        
        Returns cleaned text without HTML tags.
        """
        try:
            from bs4 import BeautifulSoup
            
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Remove script and style elements
            for script in soup(["script", "style", "nav", "footer", "header"]):
                script.decompose()
            
            # Get text
            text = soup.get_text()
            
            # Clean up whitespace
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            text = '\n'.join(chunk for chunk in chunks if chunk)
            
            logger.info(f"Extracted {len(text)} characters from HTML")
            return text
            
        except ImportError:
            logger.warning("BeautifulSoup not installed, returning raw HTML")
            return html_content
        except Exception as e:
            logger.error(f"HTML text extraction failed: {str(e)}")
            return html_content
    
    def get_text_snippet(self, text_content: str, claim_text: str, context_chars: int = 500) -> Optional[str]:
        """
        Find and extract a relevant snippet from the text related to the claim.
        
        Args:
            text_content: Full text content
            claim_text: The claim to search for
            context_chars: Number of characters to include around match
            
        Returns:
            Text snippet or None if not found
        """
        if not text_content:
            return None
        
        # Simple search - could be enhanced with semantic search
        claim_words = claim_text.lower().split()[:5]  # First 5 words
        
        for i, word in enumerate(claim_words):
            if word in text_content.lower():
                # Find position
                pos = text_content.lower().find(word)
                
                # Extract context
                start = max(0, pos - context_chars)
                end = min(len(text_content), pos + context_chars)
                
                snippet = text_content[start:end]
                logger.info(f"Found relevant snippet at position {pos}")
                return f"...{snippet}..."
        
        # No match found
        logger.warning("No relevant snippet found in text")
        return None
