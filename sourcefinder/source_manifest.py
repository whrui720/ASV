"""Persistent per-folder source manifest.

Writes a JSON record of every source resolution + download attempt into the
target folder (``datasets/`` or ``text_sources/``). Survives batch cleanup:
the downloaded files themselves are deleted after each batch, but the manifest
retains the URL cascade, format, and batch outcome so the run stays auditable.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from models import SourceManifestEntry

logger = logging.getLogger(__name__)


class SourceManifest:
    """Append-and-flush JSON writer for a single manifest file."""

    def __init__(self, path: Path, pdf_stem: str):
        self.path = path
        self.pdf_stem = pdf_stem
        self.entries: List[SourceManifestEntry] = []

    def append(self, entry: SourceManifestEntry) -> None:
        self.entries.append(entry)
        self._flush()

    def _flush(self) -> None:
        payload = {
            "pdf_stem": self.pdf_stem,
            "updated_at": datetime.now().isoformat(),
            "count": len(self.entries),
            "entries": [e.model_dump() for e in self.entries],
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to write source manifest {self.path}: {e}")

    def mark_deleted(self, citation_id: str) -> None:
        """Stamp ``deleted_at`` on the entry for this citation_id (last-write wins)."""
        for entry in reversed(self.entries):
            if entry.citation_id == citation_id and entry.deleted_at is None:
                entry.deleted_at = datetime.now().isoformat()
                self._flush()
                return
