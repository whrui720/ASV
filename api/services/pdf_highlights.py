"""PDF offset→rect resolution for claim highlighting (S5, §7).

``location_in_text`` offsets index the exact string the extractor persisted
at ``citations/{stem}_text.txt`` (B2) — slicing that string for a claim's
span gives the literal, non-paraphrased substring PyMuPDF's own text layer
was built from, so ``page.search_for()`` (literal search, tolerant of minor
whitespace differences) finds it far more reliably than searching for the
LLM's own (possibly reworded) ``claim.text``.

Two tiers, in order:
  1. Slice the persisted text at ``location_in_text.start:end``, search each
     PDF page for that literal substring.
  2. Fallback — search for ``claim.text[:120]`` directly. Covers claims with
     no ``location_in_text`` (the LLM paraphrased them) or a slice PyMuPDF's
     own text layer doesn't reproduce verbatim.

Degrades gracefully: a claim with no resolvable quads on any page is simply
omitted from the result — callers still render the sidebar/list for it.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

from models import ClaimObject
from run_paths import RunPaths

logger = logging.getLogger(__name__)

_NEEDLE_LEN = 120  # long enough to disambiguate, short enough to survive line wraps


def _search_all_pages(doc, needle: str):
    """Return [(page_num, quad), ...] on the first page the needle is found on."""
    needle = needle.strip()
    if not needle:
        return []
    for page_num, page in enumerate(doc):
        try:
            quads = page.search_for(needle, quads=True)
        except Exception:
            quads = []
        if quads:
            return [(page_num, q) for q in quads]
    return []


def resolve_highlights(run_paths: RunPaths, pdf_path: Path, claims: List[ClaimObject]) -> List[dict]:
    """Return [{claimId, page, quads: [[x0,y0,x1,y1],...]}, ...] (quads
    normalized 0..1 by page size) for every claim a match could be found for."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        logger.warning("PyMuPDF not available — highlighting disabled")
        return []

    persisted_text: Optional[str] = None
    text_path = run_paths.claims_text_path()
    if text_path.exists():
        try:
            persisted_text = text_path.read_text(encoding="utf-8")
        except Exception:
            persisted_text = None

    try:
        doc = fitz.open(str(pdf_path))
    except Exception as e:
        logger.warning(f"Could not open PDF for highlighting: {e}")
        return []

    results: List[dict] = []
    try:
        page_sizes = [(p.rect.width, p.rect.height) for p in doc]

        for claim in claims:
            needle = None
            loc = claim.location_in_text
            if persisted_text and loc and loc.start is not None and loc.end is not None:
                needle = persisted_text[loc.start:loc.end][:_NEEDLE_LEN]
            if not needle or len(needle.strip()) < 15:
                needle = claim.text[:_NEEDLE_LEN]

            hits = _search_all_pages(doc, needle)
            if not hits:
                continue

            page_num = hits[0][0]
            pw, ph = page_sizes[page_num]
            quads = [
                [q.rect.x0 / pw, q.rect.y0 / ph, q.rect.x1 / pw, q.rect.y1 / ph]
                for _, q in hits
            ]
            results.append({"claim_id": claim.claim_id, "page": page_num, "quads": quads})
    finally:
        doc.close()

    return results
