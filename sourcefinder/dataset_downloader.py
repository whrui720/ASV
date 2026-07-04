"""Dataset Downloader - Download datasets (CSV, JSON, Excel)"""

import io
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import pandas as pd
import requests

from .config import DOWNLOAD_TIMEOUT, DATASET_OUTPUT_DIR
from run_paths import RunPaths

logger = logging.getLogger(__name__)


class DatasetDownloader:
    """Download datasets (CSV, JSON, Excel).

    Content sniffing (magic bytes + content-type) determines format before
    parsing. Non-tabular payloads (PDF, HTML) are rejected with a specific
    error so the orchestrator can fall through to its next candidate URL
    rather than saving garbage.
    """

    # (format, error) — error is set when the payload is not a dataset.
    _NOT_TABULAR: Tuple[str, str] = ("__not_tabular__", "URL is not tabular data")

    def __init__(
        self,
        run_paths: Optional[RunPaths] = None,
        output_dir: Optional[str] = None,
    ):
        if run_paths is not None:
            self.output_dir = run_paths.datasets
        elif output_dir is not None:
            self.output_dir = Path(output_dir)
            self.output_dir.mkdir(parents=True, exist_ok=True)
        else:
            self.output_dir = Path(DATASET_OUTPUT_DIR)
            self.output_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        # No application/json in Accept: DOI URLs content-negotiate to
        # CrossRef bibliographic metadata when JSON is offered, which downstream
        # code would mistake for a real dataset.
        self.session.headers.update({
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/120.0.0.0 Safari/537.36'
            ),
            'Accept': (
                'text/csv,'
                'application/vnd.ms-excel,'
                'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,'
                '*/*;q=0.8'
            ),
            'Accept-Language': 'en-US,en;q=0.9',
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
            'error': None,
        }

        try:
            logger.info(f"Downloading dataset from: {url}")
            response = self.session.get(url, timeout=DOWNLOAD_TIMEOUT)
            response.raise_for_status()

            content_type = response.headers.get('content-type', '').lower()
            file_format, detected_kind = self._sniff_format(url, content_type, response.content)

            if file_format is None:
                # Non-tabular payload — reject cleanly so caller can iterate.
                err = f"URL is not tabular data (detected: {detected_kind})"
                result['error'] = err
                logger.info(f"  ✗ {err}")
                return result

            filename = f"citation_{citation_id}_dataset.{file_format}"
            local_path = self.output_dir / filename

            # Parse from already-downloaded bytes — no second HTTP fetch.
            if file_format == 'csv':
                df = pd.read_csv(io.BytesIO(response.content))
                df.to_csv(local_path, index=False)
            elif file_format == 'json':
                data = response.json()
                with open(local_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2)
            elif file_format == 'xlsx':
                df = pd.read_excel(io.BytesIO(response.content))
                df.to_excel(local_path, index=False)
            elif file_format == 'xls':
                df = pd.read_excel(io.BytesIO(response.content))
                df.to_excel(local_path, index=False)
            else:
                # Should not happen — _sniff_format returns None for unknown formats.
                result['error'] = f"Unhandled format: {file_format}"
                logger.error(f"  ✗ {result['error']}")
                return result

            result['downloaded'] = True
            result['format'] = file_format
            result['path'] = str(local_path)
            logger.info(f"✓ Downloaded to: {local_path}")

        except Exception as e:
            result['error'] = str(e)
            logger.error(f"✗ Download failed: {e}")

        return result

    @staticmethod
    def _sniff_format(
        url: str, content_type: str, content: bytes
    ) -> Tuple[Optional[str], str]:
        """
        Detect payload format from magic bytes + content-type + URL hints.

        Returns (format, kind_description). ``format`` is None when the payload
        is not a dataset we can parse; ``kind_description`` names what we
        detected so callers can surface it in error messages.
        """
        url_lower = url.lower()
        head = content[:512] if content else b""
        head_stripped = head.lstrip()

        # 1) Binary format markers — highest confidence.
        if head.startswith(b"%PDF-") or 'application/pdf' in content_type:
            return None, "application/pdf"
        if head.startswith(b"PK\x03\x04") or 'spreadsheetml' in content_type:
            # ZIP-container / OOXML. Excel .xlsx uses this too.
            if '.xls' in url_lower or 'excel' in content_type or 'spreadsheetml' in content_type:
                return 'xlsx', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            return None, "application/zip (not spreadsheet)"
        if head.startswith(b"\xd0\xcf\x11\xe0") or 'ms-excel' in content_type:
            # Legacy XLS (OLE compound file).
            return 'xls', 'application/vnd.ms-excel'

        # 2) HTML — text but not tabular.
        head_lower = head_stripped[:256].lower()
        if head_lower.startswith(b"<!doctype html") \
                or head_lower.startswith(b"<html") \
                or 'text/html' in content_type:
            return None, "text/html"

        # 3) URL + explicit content-type hints for tabular formats.
        if '.csv' in url_lower or 'text/csv' in content_type:
            return 'csv', 'text/csv'
        if '.json' in url_lower or 'application/json' in content_type:
            # Parse-check: real JSON datasets are dict/list at top level.
            # If it's a JSON but starts with metadata patterns, we still accept
            # — script validator can inspect it. Content sniffing to catch
            # non-dataset JSON is out of scope; DOI content-negotiation is
            # already blocked upstream by dropping application/json from Accept.
            return 'json', 'application/json'
        if '.xlsx' in url_lower:
            return 'xlsx', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        if '.xls' in url_lower:
            return 'xls', 'application/vnd.ms-excel'

        # 4) Content-based guess for un-hinted text payloads.
        if head_stripped.startswith(b"{") or head_stripped.startswith(b"["):
            try:
                json.loads(content.decode("utf-8", errors="strict"))
                return 'json', 'application/json (sniffed)'
            except (UnicodeDecodeError, json.JSONDecodeError):
                pass
        # CSV heuristic: first non-empty line contains commas and decodes as text.
        try:
            text_head = head.decode("utf-8", errors="strict")
            first_line = next(
                (ln for ln in text_head.splitlines() if ln.strip()), ""
            )
            if first_line and first_line.count(",") >= 1:
                return 'csv', 'text/csv (sniffed)'
        except UnicodeDecodeError:
            pass

        return None, content_type or "unknown"

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
