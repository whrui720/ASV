"""Dataset Downloader - Download datasets (CSV, JSON, Excel)"""

import io
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import pandas as pd

from .config import DOWNLOAD_TIMEOUT, DATASET_OUTPUT_DIR, MAX_FILE_SIZE_MB
from .polite_http import PoliteSession
from asv.core.run_paths import RunPaths

logger = logging.getLogger(__name__)

#: A payload with one column is a list, not a dataset a script can cross-check a
#: statistic against. SOURCE_ACQUISITION.md F10: 12 of 14 dataset "successes" in
#: the measured run were Crossref bibliographic records that parsed as JSON.
MIN_TABULAR_COLUMNS = 2
MIN_TABULAR_ROWS = 1


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
        self.session = PoliteSession()
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
            body, content_type, size_error = self._fetch_bounded(url)
            if size_error:
                result['error'] = size_error
                logger.info(f"  ✗ {size_error}")
                return result

            file_format, detected_kind = self._sniff_format(url, content_type, body)

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
                df = pd.read_csv(io.BytesIO(body))
                shape_error = self._check_frame(df)
                if shape_error:
                    result['error'] = shape_error
                    logger.info(f"  ✗ {shape_error}")
                    return result
                df.to_csv(local_path, index=False)
            elif file_format == 'json':
                data = json.loads(body.decode('utf-8', errors='replace'))
                shape_error = self._check_json(data)
                if shape_error:
                    result['error'] = shape_error
                    logger.info(f"  ✗ {shape_error}")
                    return result
                with open(local_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2)
            elif file_format in ('xlsx', 'xls'):
                df = pd.read_excel(io.BytesIO(body))
                shape_error = self._check_frame(df)
                if shape_error:
                    result['error'] = shape_error
                    logger.info(f"  ✗ {shape_error}")
                    return result
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

    def _fetch_bounded(self, url: str) -> Tuple[bytes, str, Optional[str]]:
        """Fetch *url*, refusing to pull more than ``MAX_FILE_SIZE_MB`` into memory.

        ``MAX_FILE_SIZE_MB`` was dead config — declared, documented, referenced
        nowhere, with the whole body read into memory regardless (F10). The cap
        is checked twice because a server that omits ``Content-Length`` is
        exactly the one likely to stream something enormous.
        """
        cap = MAX_FILE_SIZE_MB * 1024 * 1024
        response = self.session.stream_get(url, timeout=DOWNLOAD_TIMEOUT)
        with response:
            response.raise_for_status()
            content_type = response.headers.get('content-type', '').lower()

            declared = response.headers.get('content-length')
            if declared and declared.isdigit() and int(declared) > cap:
                return b"", content_type, (
                    f"Dataset is {int(declared) / 1048576:.0f} MB, over the "
                    f"{MAX_FILE_SIZE_MB} MB limit"
                )

            chunks = []
            total = 0
            for chunk in response.iter_content(chunk_size=65536):
                if not chunk:
                    continue
                total += len(chunk)
                if total > cap:
                    return b"", content_type, (
                        f"Dataset exceeded the {MAX_FILE_SIZE_MB} MB limit while "
                        f"downloading"
                    )
                chunks.append(chunk)
        return b"".join(chunks), content_type, None

    @staticmethod
    def _check_frame(df: "pd.DataFrame") -> Optional[str]:
        """Reject payloads that parsed but are not a table.

        A one-column CSV or an empty frame will let the generated validation
        script run and produce a confident answer from nothing.
        """
        rows, cols = df.shape
        if rows < MIN_TABULAR_ROWS or cols < MIN_TABULAR_COLUMNS:
            return (
                f"Parsed but not tabular: {rows} row(s) x {cols} column(s), "
                f"need at least {MIN_TABULAR_ROWS}x{MIN_TABULAR_COLUMNS}"
            )
        return None

    @staticmethod
    def _check_json(data: Any) -> Optional[str]:
        """Same check for JSON, which is where the false positives actually came from.

        The measured run recorded 12 dataset "successes" that were Crossref
        bibliographic records: valid JSON, a dict at the top level, no rows.
        Dropping ``application/json`` from the Accept header closed that one
        route; this closes the shape.
        """
        if isinstance(data, list):
            if len(data) < MIN_TABULAR_ROWS:
                return "Parsed but not tabular: empty JSON array"
            first = data[0]
            if isinstance(first, dict) and len(first) >= MIN_TABULAR_COLUMNS:
                return None
            return "Parsed but not tabular: JSON array is not a list of records"
        if isinstance(data, dict):
            # A dict of equal-length columns is a table; anything else (a
            # bibliographic record, an API envelope) is not.
            columns = [v for v in data.values() if isinstance(v, list)]
            if len(columns) >= MIN_TABULAR_COLUMNS and all(
                len(c) >= MIN_TABULAR_ROWS for c in columns
            ):
                return None
            for value in data.values():
                if isinstance(value, list) and value and isinstance(value[0], dict) \
                        and len(value[0]) >= MIN_TABULAR_COLUMNS:
                    return None  # {"records": [{...}, ...]} — a common envelope
            return "Parsed but not tabular: JSON object carries no record array"
        return "Parsed but not tabular: JSON is a scalar"

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
