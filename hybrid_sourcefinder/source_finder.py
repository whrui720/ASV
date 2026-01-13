"""
Source Finder - Download datasets for quantitative claims with citations

Handles downloading of datasets (CSV, JSON, Excel, etc.) from various sources
including academic repositories, government data portals, and direct URLs.
"""

import requests
import pandas as pd
from pathlib import Path
from typing import Optional, Dict, Any
from urllib.parse import urlparse
import json
import tempfile
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class SourceFinder:
    """
    Downloads datasets from citation URLs for quantitative claims.
    
    Supports:
    - Direct CSV/JSON/Excel downloads
    - DOI resolution to data repositories
    - Common data portals (data.gov, Kaggle, etc.)
    """
    
    def __init__(self, output_dir: str = "./data"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    def download_dataset(self, url: str, claim_id: str) -> Dict[str, Any]:
        """
        Download dataset from URL.
        
        Args:
            url: URL to download from
            claim_id: Unique identifier for the claim
            
        Returns:
            Dict with download status and metadata:
            {
                'downloaded': bool,
                'data_format': str,
                'platform': str,
                'source_url': str,
                'local_path': str,
                'error': str (if failed)
            }
        """
        result = {
            'downloaded': False,
            'data_format': None,
            'platform': 'pandas',
            'source_url': url,
            'local_path': None,
            'error': None
        }
        
        try:
            # Handle DOI URLs
            if 'doi.org' in url:
                logger.info(f"Resolving DOI: {url}")
                resolved_url = self._resolve_doi(url)
                if not resolved_url:
                    result['error'] = "Could not resolve DOI to downloadable dataset"
                    return result
                url = resolved_url
            
            # Try to download the file
            logger.info(f"Downloading from: {url}")
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            
            # Detect file format
            content_type = response.headers.get('content-type', '').lower()
            file_format = self._detect_format(url, content_type)
            
            # Save the file
            filename = f"claim_{claim_id}_dataset.{file_format}"
            local_path = self.output_dir / filename
            
            # Try to parse and validate the data
            if file_format == 'csv':
                df = pd.read_csv(url)
                df.to_csv(local_path, index=False)
            elif file_format == 'json':
                data = response.json()
                with open(local_path, 'w') as f:
                    json.dump(data, f, indent=2)
            elif file_format in ['xlsx', 'xls']:
                df = pd.read_excel(url)
                df.to_excel(local_path, index=False)
            else:
                # Save as binary for unknown formats
                with open(local_path, 'wb') as f:
                    f.write(response.content)
            
            result['downloaded'] = True
            result['data_format'] = file_format
            result['local_path'] = str(local_path)
            logger.info(f"✓ Successfully downloaded dataset to {local_path}")
            
        except requests.exceptions.RequestException as e:
            result['error'] = f"Network error: {str(e)}"
            logger.error(f"✗ Download failed: {str(e)}")
        except pd.errors.ParserError as e:
            result['error'] = f"Data parsing error: {str(e)}"
            logger.error(f"✗ Failed to parse data: {str(e)}")
        except Exception as e:
            result['error'] = f"Unexpected error: {str(e)}"
            logger.error(f"✗ Unexpected error: {str(e)}")
        
        return result
    
    def download_from_citation(self, citation_details: Dict[str, Any], claim_id: str) -> Dict[str, Any]:
        """
        Download dataset from citation details.
        
        Args:
            citation_details: Citation metadata (url, doi, title, etc.)
            claim_id: Unique identifier for the claim
            
        Returns:
            Download result dict
        """
        # Try URL first
        if citation_details.get('url'):
            return self.download_dataset(citation_details['url'], claim_id)
        
        # Try DOI
        if citation_details.get('doi'):
            doi_url = f"https://doi.org/{citation_details['doi']}"
            return self.download_dataset(doi_url, claim_id)
        
        # No downloadable source found
        return {
            'downloaded': False,
            'data_format': None,
            'platform': None,
            'source_url': None,
            'local_path': None,
            'error': 'No URL or DOI found in citation details'
        }
    
    def _resolve_doi(self, doi_url: str) -> Optional[str]:
        """
        Resolve DOI to actual data URL.
        
        Returns direct download URL if available, None otherwise.
        """
        try:
            response = self.session.get(doi_url, allow_redirects=True, timeout=10)
            
            # Check if redirected to a data repository
            final_url = response.url
            
            # Common patterns for direct data links
            if any(pattern in final_url for pattern in ['.csv', '.json', '.xlsx', 'download', 'data']):
                return final_url
            
            # For now, return the resolved URL - could enhance with scraping
            return final_url
            
        except Exception as e:
            logger.warning(f"DOI resolution failed: {str(e)}")
            return None
    
    def _detect_format(self, url: str, content_type: str) -> str:
        """
        Detect file format from URL and content type.
        """
        # Check URL extension
        url_lower = url.lower()
        if '.csv' in url_lower or 'text/csv' in content_type:
            return 'csv'
        elif '.json' in url_lower or 'application/json' in content_type:
            return 'json'
        elif '.xlsx' in url_lower or 'spreadsheetml' in content_type:
            return 'xlsx'
        elif '.xls' in url_lower or 'ms-excel' in content_type:
            return 'xls'
        
        # Default to CSV
        return 'csv'
    
    def validate_dataset(self, local_path: str) -> bool:
        """
        Validate that downloaded dataset is readable.
        
        Returns True if dataset can be loaded successfully.
        """
        try:
            file_path = Path(local_path)
            
            if file_path.suffix == '.csv':
                df = pd.read_csv(file_path)
            elif file_path.suffix == '.json':
                with open(file_path) as f:
                    data = json.load(f)
            elif file_path.suffix in ['.xlsx', '.xls']:
                df = pd.read_excel(file_path)
            else:
                # Unknown format, assume valid
                return True
            
            logger.info(f"✓ Dataset validated successfully")
            return True
            
        except Exception as e:
            logger.error(f"✗ Dataset validation failed: {str(e)}")
            return False
