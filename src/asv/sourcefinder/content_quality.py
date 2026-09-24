"""Content-quality gate — Tier 0.3 (docs/TIER0_PLAN.md §4).

A successful HTTP fetch is a necessary but not sufficient signal. In
``runs/hsv_cancer__20260706_192057``, 10 of 16 "successful" downloads were
publisher landing pages — abstract plus reference list. They clear any length
floor (an abstract plus 60 references is several thousand characters), and RAG
then searches a document that cannot contain the evidence.

This classifier decides whether fetched text is admissible as evidence. It is
**deterministic and LLM-free on purpose**: VALUE_PROPOSITION.md §5/L4 observes
that statcheck is trusted precisely because it abstains deterministically
wherever it cannot be certain. A gate whose job is to decide what counts as
evidence must not itself be a probabilistic judgment, and it must be
explainable in one line to a user who disagrees with it.

Every threshold here is a starting point to be calibrated against hand labels —
see ``scripts/calibrate_content_quality.py``.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from asv.core.verdicts import ContentQuality

from .config import (
    CQ_ABSTRACT_MAX_CHARS,
    CQ_FULL_TEXT_MIN_CHARS,
    CQ_MIN_USABLE_CHARS,
    CQ_PAYWALL_MAX_CHARS,
    CQ_REF_LINE_FRACTION,
    CQ_STRONG_IMRAD_SECTIONS,
    CQ_WEAK_IMRAD_SECTIONS,
)

# Re-exported so the import path named in TIER0_PLAN.md Appendix A works; the
# enum itself lives in core (see the layering note in asv/core/verdicts.py).
__all__ = ["ContentQuality", "ContentAssessment", "assess_content"]


# ---------------------------------------------------------------------------
# Signal 1 — IMRaD structure. The strongest single discriminator: a research
# article has these as standalone headings; a landing page has "Abstract",
# "References", "Similar content being viewed by others", "Author information".
# ---------------------------------------------------------------------------

_IMRAD_SECTIONS: Dict[str, tuple[str, ...]] = {
    "introduction": ("introduction", "background"),
    "methods": (
        "methods", "method", "methodology",
        "materials and methods", "material and methods",
        "patients and methods", "subjects and methods",
        "experimental procedures", "experimental section",
        "materials & methods",
    ),
    "results": ("results", "results and discussion", "findings"),
    "discussion": ("discussion", "general discussion"),
    "conclusion": ("conclusion", "conclusions", "concluding remarks"),
    "acknowledgements": (
        "acknowledgement", "acknowledgements",
        "acknowledgment", "acknowledgments",
    ),
}

# Leading section numbering a heading may carry: "3.", "3.1", "III.", "IV -"
_HEADING_PREFIX_RE = re.compile(
    r"^\s*(?:(?:\d+|[ivxlcdm]+)\s*[.)\-:]\s*)*", re.IGNORECASE
)
_HEADING_TRIM_RE = re.compile(r"[\s.:;\-–—*#]+$")

# A heading is short. Anything long is prose that happens to start with the word.
_MAX_HEADING_CHARS = 60


# ---------------------------------------------------------------------------
# Signal 2 — paywall interstitials. These strings are publisher-specific and
# remarkably stable.
# ---------------------------------------------------------------------------

_PAYWALL_PHRASES = (
    "this is a preview of subscription content",
    "access through your institution",
    "access via your institution",
    "buy this article",
    "buy article pdf",
    "purchase access",
    "subscribe to this journal",
    "subscribe to journal",
    "rent or buy article",
    "rent this article",
    "get full journal access",
    "get time limited or full article access",
    "immediate online access to all issues",
    "sign in to read the full article",
    "sign in to access",
    "log in to view the full text",
    "institutional login",
    "add to cart",
    "you do not have access",
    "access denied",
    "please verify you are a human",
    "checking your browser before accessing",
    "enable javascript to view",
)

_PRICE_RE = re.compile(r"(?:US\s?\$|USD\s?|\$|€|£)\s?\d{1,3}(?:[.,]\d{2})\b")


# ---------------------------------------------------------------------------
# Signal 3 — reference-list dominance. A landing page is mostly its own
# bibliography; a full text is not.
# ---------------------------------------------------------------------------

_REF_LINE_RE = re.compile(
    r"^\s*\[?\d{1,3}[\].)]?\s+\S+.*\b(?:19|20)\d{2}\b"
)


# ---------------------------------------------------------------------------
# Signal 4 — abstract marker
# ---------------------------------------------------------------------------

_ABSTRACT_MARKERS = ("abstract", "summary", "graphical abstract")
_REFERENCES_MARKERS = ("references", "bibliography", "literature cited", "works cited")


@dataclass(frozen=True)
class ContentAssessment:
    """Verdict on whether fetched text is admissible as evidence.

    ``signals`` carries every value the classifier looked at. It is persisted on
    the manifest so a mis-tuned threshold is diagnosable after the fact rather
    than requiring a re-fetch.
    """
    quality: ContentQuality
    reason: str
    signals: Dict[str, Any] = field(default_factory=dict)

    @property
    def judgeable(self) -> bool:
        return self.quality == ContentQuality.FULL_TEXT


def _normalise_line(line: str) -> str:
    line = unicodedata.normalize("NFKC", line).strip()
    line = _HEADING_PREFIX_RE.sub("", line)
    line = _HEADING_TRIM_RE.sub("", line)
    return line.lower().strip()


def _count_imrad_sections(lines: list[str]) -> tuple[int, list[str]]:
    """Return (distinct section count, section names) for standalone headings."""
    found: set[str] = set()
    for raw in lines:
        if len(raw) > _MAX_HEADING_CHARS:
            continue
        norm = _normalise_line(raw)
        if not norm or len(norm) > _MAX_HEADING_CHARS:
            continue
        for section, aliases in _IMRAD_SECTIONS.items():
            if norm in aliases:
                found.add(section)
                break
    return len(found), sorted(found)


def _reference_line_fraction(lines: list[str]) -> float:
    non_empty = [ln for ln in lines if ln.strip()]
    if not non_empty:
        return 0.0
    hits = sum(1 for ln in non_empty if _REF_LINE_RE.match(ln))
    return hits / len(non_empty)


def _has_marker(lines: list[str], markers: tuple[str, ...]) -> bool:
    for raw in lines:
        if len(raw) > _MAX_HEADING_CHARS:
            continue
        if _normalise_line(raw) in markers:
            return True
    return False


def assess_content(
    text: Optional[str],
    *,
    file_format: Optional[str] = None,
    page_count: Optional[int] = None,
    url: Optional[str] = None,
) -> ContentAssessment:
    """Classify extracted source text as evidence.

    Decision order matters. The **default is the abstaining class**: an unknown
    page that is really full text becomes a false abstention (costly, safe, and
    visible in the checkable-rate metric), whereas an unknown landing page
    classified ``full_text`` becomes a false accusation — the risk
    VALUE_PROPOSITION.md §10 rates critical. Bias toward abstention, then buy
    the threshold back with the gold set.
    """
    body = (text or "")
    usable_chars = len(body.strip())
    lines = body.splitlines()

    imrad_count, imrad_sections = _count_imrad_sections(lines)
    ref_fraction = _reference_line_fraction(lines)
    lowered = body.lower()
    paywall_hits = [p for p in _PAYWALL_PHRASES if p in lowered]
    price_hit = bool(_PRICE_RE.search(body))
    has_abstract = _has_marker(lines, _ABSTRACT_MARKERS)
    has_references = _has_marker(lines, _REFERENCES_MARKERS)

    signals: Dict[str, Any] = {
        "usable_chars": usable_chars,
        "imrad_sections": imrad_sections,
        "imrad_count": imrad_count,
        "reference_line_fraction": round(ref_fraction, 3),
        "paywall_phrases": paywall_hits,
        "price_marker": price_hit,
        "has_abstract_marker": has_abstract,
        "has_references_marker": has_references,
        "page_count": page_count,
        "format": file_format,
        "url": url,
    }

    def out(quality: ContentQuality, reason: str) -> ContentAssessment:
        return ContentAssessment(quality=quality, reason=reason, signals=signals)

    # 1. Nothing usable. This is the pre-Tier-0 200-char gate, now typed —
    #    it keeps its old job (delete the file, let the cascade continue) and
    #    nothing more.
    if usable_chars < CQ_MIN_USABLE_CHARS:
        return out(
            ContentQuality.REJECTED,
            f"only {usable_chars} usable characters extracted "
            f"(floor is {CQ_MIN_USABLE_CHARS})",
        )

    # 2. Paywall / bot interstitial. A short page that is advertising access is
    #    not evidence, however many characters it has.
    if (paywall_hits or price_hit) and usable_chars < CQ_PAYWALL_MAX_CHARS:
        marker = paywall_hits[0] if paywall_hits else "a price marker"
        return out(
            ContentQuality.PAYWALL_INTERSTITIAL,
            f"access-wall page ({usable_chars} chars, matched {marker!r})",
        )

    # 3. Strong structure: three or more IMRaD sections is a research article
    #    regardless of length (letters and brief communications are short).
    if imrad_count >= CQ_STRONG_IMRAD_SECTIONS:
        return out(
            ContentQuality.FULL_TEXT,
            f"{imrad_count} IMRaD sections present ({', '.join(imrad_sections)})",
        )

    # 4. Weaker structure, corroborated by size or page count.
    if imrad_count >= CQ_WEAK_IMRAD_SECTIONS and (
        usable_chars >= CQ_FULL_TEXT_MIN_CHARS or (page_count or 0) >= 4
    ):
        return out(
            ContentQuality.FULL_TEXT,
            f"{imrad_count} IMRaD sections with {usable_chars} chars"
            + (f" across {page_count} pages" if page_count else ""),
        )

    # 5. Reference-list dominance without structure: a landing page.
    if ref_fraction > CQ_REF_LINE_FRACTION and imrad_count < CQ_WEAK_IMRAD_SECTIONS:
        return out(
            ContentQuality.ABSTRACT_ONLY,
            f"{ref_fraction:.0%} of lines are bibliography entries and no IMRaD "
            f"structure — this looks like an abstract + reference list",
        )

    # 6. Too short to be a full article.
    if usable_chars < CQ_ABSTRACT_MAX_CHARS:
        return out(
            ContentQuality.ABSTRACT_ONLY,
            f"{usable_chars} chars with {imrad_count} IMRaD section(s) — too short "
            f"for a full article",
        )

    # 7. Conservative default. We could not positively identify full text, so we
    #    abstain rather than judge a claim against something that may be an
    #    abstract.
    return out(
        ContentQuality.ABSTRACT_ONLY,
        f"could not confirm full text ({usable_chars} chars, {imrad_count} IMRaD "
        f"section(s)); defaulting to abstention",
    )
