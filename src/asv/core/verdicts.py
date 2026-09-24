"""The verdict vocabulary — Tier 0.2 (docs/TIER0_PLAN.md §2).

This module is the single source of truth for *what ASV is allowed to say about a
claim*. It replaces the ``passed: bool`` that conflated "the source contradicts
this" with "the source is paywalled" — two outputs that imply opposite user
actions.

Layering note (deviation from TIER0_PLAN.md §2.2 / Appendix A): the plan placed
``ContentQuality`` in ``sourcefinder/content_quality.py`` and ``ReferenceStatus`` /
``RetractionStatus`` in ``sourcefinder/reference_verifier.py``. Both are referenced
by ``core/models.py``, and ``core`` must not import from ``sourcefinder`` (every
other package depends on ``core``, never the reverse). All shared enums therefore
live here; the sourcefinder modules import and re-export them, so the import paths
the plan names still work.
"""

from __future__ import annotations

from enum import Enum


class Verdict(str, Enum):
    """What ASV concluded about one claim.

    Exactly one of these lands on every ``ValidationResult``. The four
    non-abstention values are *judgments about the claim* and, per Tier 0.5,
    may only be emitted with a verbatim-verified evidence span plus a
    resolvable source URL. ``NOT_CHECKABLE`` is an abstention and carries a
    ``NotCheckableReason`` instead of a confidence.
    """

    SUBSTANTIATED = "substantiated"
    PARTIALLY_SUBSTANTIATED = "partially_substantiated"
    NOT_SUBSTANTIATED = "not_substantiated"
    CONTRADICTED = "contradicted"
    NOT_CHECKABLE = "not_checkable"


class NotCheckableReason(str, Enum):
    """Why ASV declined to judge a claim.

    The reason is what tells a user what to *do*: ``abstract_only`` means "find
    the full text", ``reference_not_found`` means "check your bibliography",
    ``source_download_failed`` means "try again or log in". Collapsing these into
    one ``failed`` is the defect Tier 0.2 exists to fix.
    """

    # 0.1 — no source exists to check against
    NO_SOURCE_AVAILABLE = "no_source_available"
    ORIGINAL_CONTRIBUTION = "original_contribution"
    # acquisition
    SOURCE_NOT_RESOLVED = "source_not_resolved"
    SOURCE_DOWNLOAD_FAILED = "source_download_failed"
    # 0.3 — bytes arrived, but they are not judgeable evidence
    ABSTRACT_ONLY = "abstract_only"
    PAYWALL_INTERSTITIAL = "paywall_interstitial"
    CONTENT_REJECTED = "content_rejected"
    # 0.5 — judgment could not be evidenced
    RETRIEVAL_EMPTY = "retrieval_empty"
    EVIDENCE_UNVERIFIABLE = "evidence_unverifiable"
    # 0.6 — the reference itself
    REFERENCE_NOT_FOUND = "reference_not_found"
    REFERENCE_UNVERIFIED = "reference_unverified"
    # catch-alls
    UNRESOLVABLE_BY_DESIGN = "unresolvable_by_design"
    VALIDATION_ERROR = "validation_error"


class ContentQuality(str, Enum):
    """How good the fetched source text is as evidence — Tier 0.3.

    A successful HTTP fetch is necessary but not sufficient. Publisher landing
    pages (abstract + reference list) clear any length floor and then get
    RAG-searched for evidence they cannot contain.
    """

    FULL_TEXT = "full_text"
    ABSTRACT_ONLY = "abstract_only"
    PAYWALL_INTERSTITIAL = "paywall_interstitial"
    REJECTED = "rejected"


class ReferenceStatus(str, Enum):
    """Whether the cited reference exists in the scholarly record — Tier 0.6.

    ``NOT_FOUND_IN_INDEXES`` is deliberately *not* named "fabricated". Saying a
    real reference does not exist is an allegation; the enum, the explanation
    strings, and the UI all say only what was actually observed — that the
    named indexes did not return a match.
    """

    VERIFIED = "verified"
    AMBIGUOUS = "ambiguous"
    NOT_FOUND_IN_INDEXES = "not_found_in_indexes"
    UNINDEXED_BY_DESIGN = "unindexed_by_design"
    UNVERIFIED = "unverified"


class RetractionStatus(str, Enum):
    """Retraction / correction state of a cited source — Tier 0.6.

    Orthogonal to the claim verdict: a retracted paper can still literally
    contain the sentence being cited, so this raises a flag rather than
    changing a verdict.
    """

    NONE = "none"
    RETRACTED = "retracted"
    CONCERN_RAISED = "concern_raised"
    CORRECTED = "corrected"
    UNKNOWN = "unknown"


# --------------------------------------------------------------------------
# Verdict sets — first-class so the evidence invariant (models.py), the eval
# harness (scripts/eval_gold.py) and any future escalation policy all share
# one definition.
# --------------------------------------------------------------------------

#: Verdicts that assert a defect in the citation. These are *allegations*, and
#: VALUE_PROPOSITION.md §10 rates false accusation the critical risk — so any
#: policy that wants to be extra careful before speaking keys off this set.
ACCUSATION_VERDICTS = frozenset({
    Verdict.NOT_SUBSTANTIATED,
    Verdict.CONTRADICTED,
})

#: Verdicts that are judgments about the claim, as opposed to abstentions.
#: Tier 0.5: every one of these requires a verbatim-verified evidence span and
#: a resolvable source URL, enforced in ``ValidationResult``.
EVIDENCED_VERDICTS = frozenset({
    Verdict.SUBSTANTIATED,
    Verdict.PARTIALLY_SUBSTANTIATED,
    Verdict.NOT_SUBSTANTIATED,
    Verdict.CONTRADICTED,
})

#: Content qualities ASV is willing to judge against. Tier 0.3: an abstract is
#: not evidence about a claim that lives in the Results section.
JUDGEABLE_CONTENT = frozenset({ContentQuality.FULL_TEXT})

#: Ranking used by ``TextDownloader.download_with_resolution`` to keep the best
#: candidate rather than the first (TIER0_PLAN.md §4.4). Higher is better.
CONTENT_QUALITY_RANK = {
    ContentQuality.REJECTED: 0,
    ContentQuality.PAYWALL_INTERSTITIAL: 1,
    ContentQuality.ABSTRACT_ONLY: 2,
    ContentQuality.FULL_TEXT: 3,
}

#: ``ContentQuality`` -> the abstention reason to report when we refuse to judge
#: against it.
CONTENT_QUALITY_REASON = {
    ContentQuality.ABSTRACT_ONLY: NotCheckableReason.ABSTRACT_ONLY,
    ContentQuality.PAYWALL_INTERSTITIAL: NotCheckableReason.PAYWALL_INTERSTITIAL,
    ContentQuality.REJECTED: NotCheckableReason.CONTENT_REJECTED,
}


def content_quality_rank(quality: "ContentQuality | None") -> int:
    """Sortable rank for a (possibly missing) content quality."""
    if quality is None:
        return -1
    return CONTENT_QUALITY_RANK.get(quality, -1)


def is_judgeable(quality: "ContentQuality | None") -> bool:
    """True when ASV is willing to judge a claim against this content."""
    return quality in JUDGEABLE_CONTENT
