"""Dataset Downloader - Download datasets (CSV, JSON, Excel)"""

import logging
import requests
import pandas as pd
import json
from pathlib import Path
from typing import Dict, Any
from .config import DOWNLOAD_TIMEOUT, DATASET_OUTPUT_DIR

logger = logging.getLogger(__name__)


class DatasetDownloader:
    """Download datasets (CSV, JSON, Excel)"""
    
    def __init__(self, output_dir: str = DATASET_OUTPUT_DIR):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    def download(self, url: str, citation_id: str) -> Dict[str, Any]:
        """
        Download dataset from URL.
        Returns: {downloaded: bool, format: str, path: str, error: str}
        """
        result = {
            'downloaded': False,
            'format': None,
            'path': None,
            'error': None
        }
        
        try:
            logger.info(f"Downloading dataset from: {url}")
            response = self.session.get(url, timeout=DOWNLOAD_TIMEOUT)
            response.raise_for_status()
            
            # Detect format
            content_type = response.headers.get('content-type', '').lower()
            file_format = self._detect_format(url, content_type)
            
            # Save file
            filename = f"citation_{citation_id}_dataset.{file_format}"
            local_path = self.output_dir / filename
            
            # Try to parse and save based on format
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
                # Save as binary
                with open(local_path, 'wb') as f:
                    f.write(response.content)
            
            result['downloaded'] = True
            result['format'] = file_format
            result['path'] = str(local_path)
            logger.info(f"✓ Downloaded to: {local_path}")
            
        except Exception as e:
            result['error'] = str(e)
            logger.error(f"✗ Download failed: {e}")
        
        return result
    
    def _detect_format(self, url: str, content_type: str) -> str:
        """Detect file format from URL and content type"""
        url_lower = url.lower()
        
        if '.csv' in url_lower or 'text/csv' in content_type:
            return 'csv'
        elif '.json' in url_lower or 'application/json' in content_type:
            return 'json'
        elif '.xlsx' in url_lower or 'spreadsheetml' in content_type:
            return 'xlsx'
        elif '.xls' in url_lower or 'ms-excel' in content_type:
            return 'xls'
        
        return 'csv'  # Default
    
    def delete_dataset(self, filename: str) -> Dict[str, Any]:
        """
        Delete a dataset file from the datasets folder.
        
        Args:
            filename: Name of the file to delete (e.g., "citation_123_dataset.csv")
        
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
            logger.info(f"✓ Deleted dataset: {file_path}")
            
        except Exception as e:
            result['error'] = str(e)
            logger.error(f"✗ Delete failed: {e}")
        
        return result
