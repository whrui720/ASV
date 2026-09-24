"""Tier 0.6 — does the cited reference exist, and has it been retracted?

The safety property under test throughout: **saying a real reference does not
exist is an allegation of fabrication**, and is the worst output this tool can
produce. The controls that prevent it — a two-index quorum, type routing for
under-indexed reference kinds, and an explicit "we could not check" state — are
each pinned here.

No network. Every index response is a fixture.
"""

import pytest

from asv.core.verdicts import ReferenceStatus, RetractionStatus
from asv.sourcefinder.index_clients import IndexRecord, IndexResponse
from asv.sourcefinder.reference_verifier import (
    ReferenceVerifier, journal_similarity, title_similarity,
)

pytestmark = pytest.mark.unit


REAL_TITLE = "Glycoprotein C of herpes simplex virus type 1 plays a principal role in the adsorption of virus to cells"

HEROLD_REF = (
    "Herold BC, WuDunn D, Soltys N, Spear PG. Glycoprotein C of herpes simplex "
    "virus type 1 plays a principal role in the adsorption of virus to cells and "
    "in infectivity. J Virol 1991; 65: 1090-1098."
)

# Reference [1] of the test corpus: a chapter in Harrison's Principles of
# Internal Medicine. Real, fine, and not in Crossref. The canonical false
# positive this module exists to avoid.
HARRISON_REF = (
    "Lerner AM. Infections with herpes simplex virus. In: Adams RD, Braunwald E, "
    "Petersdorf RG, Wilson JD (eds). Harrison's Principles of Internal Medicine. "
    "McGraw-Hill, 1983."
)


class FakeIndexes:
    """Scripted stand-in for ``BibliographicIndexes``."""

    def __init__(self, records=None, *, down=(), responses=None):
        self._records = records or []
        self._down = set(down)
        self._responses = responses or {}
        self.called = []

    def _answer(self, index):
        self.called.append(index)
        if index in self._responses:
            return self._responses[index]
        if index in self._down:
            return IndexResponse(index, responded=False, error="timeout")
        return IndexResponse(index, responded=True, records=list(self._records))

    def crossref_by_doi(self, doi):
        return self._answer("crossref")

    def crossref_bibliographic(self, query):
        return self._answer("crossref")

    def openalex_by_doi(self, doi):
        return self._answer("openalex")

    def openalex_by_title(self, title):
        return self._answer("openalex")

    def europepmc(self, query):
        return self._answer("europepmc")

    def pubmed_ecitmatch(self, **kwargs):
        return self._answer("pubmed")

    def pubmed_esearch(self, term):
        return self._answer("pubmed")

    def datacite(self, query):
        return self._answer("datacite")


def _verifier(indexes, parsed, tmp_path):
    return ReferenceVerifier(
        parse_citation=lambda _: parsed,
        indexes=indexes,
        cache_path=tmp_path / "refcheck.json",
    )


HEROLD_PARSED = {
    "title": REAL_TITLE,
    "first_author": "Herold",
    "year": 1991,
    "journal": "J Virol",
    "volume": "65",
    "first_page": "1090",
    "type": "journal-article",
}


def _match(**kwargs):
    base = dict(
        index="crossref", title=REAL_TITLE, authors=["Herold", "WuDunn", "Spear"],
        year=1991, doi="10.1128/jvi.65.3.1090-1098.1991",
        container="Journal of Virology",
    )
    base.update(kwargs)
    return IndexRecord(**base)


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def test_exact_title_and_author_verifies(tmp_path):
    v = _verifier(FakeIndexes([_match()]), HEROLD_PARSED, tmp_path)
    check = v.verify("3", HEROLD_REF)
    assert check.status == ReferenceStatus.VERIFIED
    assert check.matched_doi == "10.1128/jvi.65.3.1090-1098.1991"
    assert check.matched_url.startswith("https://doi.org/")


def test_year_off_by_one_still_verifies(tmp_path):
    """Publication-year drift between print and online is routine and must not
    turn a real reference into a finding."""
    v = _verifier(FakeIndexes([_match(year=1992)]), HEROLD_PARSED, tmp_path)
    assert v.verify("3", HEROLD_REF).status == ReferenceStatus.VERIFIED


def test_title_match_with_wrong_author_and_year_is_ambiguous(tmp_path):
    v = _verifier(
        FakeIndexes([_match(authors=["Nobody"], year=1850)]), HEROLD_PARSED, tmp_path,
    )
    assert v.verify("3", HEROLD_REF).status == ReferenceStatus.AMBIGUOUS


def test_near_miss_is_always_reported(tmp_path):
    """Even when rejecting, a reader must see the closest candidate — that is
    what turns "not found" into "your year is wrong" in ten seconds."""
    v = _verifier(
        FakeIndexes([_match(title="An entirely different paper about crop rotation")]),
        HEROLD_PARSED, tmp_path,
    )
    check = v.verify("3", HEROLD_REF)
    assert check.status == ReferenceStatus.NOT_FOUND_IN_INDEXES
    assert check.near_miss is not None
    assert check.near_miss["title"]
    assert check.near_miss["score"] is not None


# ---------------------------------------------------------------------------
# False-accusation controls
# ---------------------------------------------------------------------------

def test_single_responding_index_cannot_produce_not_found(tmp_path):
    """The two-index quorum: an outage must never read as an accusation."""
    indexes = FakeIndexes([], down=("openalex", "europepmc", "pubmed", "datacite"))
    check = _verifier(indexes, HEROLD_PARSED, tmp_path).verify("3", HEROLD_REF)
    assert check.status == ReferenceStatus.UNVERIFIED
    assert check.indexes_responded == ["crossref"]


def test_total_outage_is_unverified_not_not_found(tmp_path):
    indexes = FakeIndexes([], down=("crossref", "openalex", "europepmc", "pubmed", "datacite"))
    check = _verifier(indexes, HEROLD_PARSED, tmp_path).verify("3", HEROLD_REF)
    assert check.status == ReferenceStatus.UNVERIFIED
    assert check.indexes_responded == []


def test_textbook_chapter_is_unindexed_by_design(tmp_path):
    """Reference [1] of the test corpus. It is real; Crossref does not carry it."""
    parsed = {
        "title": "Infections with herpes simplex virus",
        "first_author": "Lerner", "year": 1983, "type": "chapter",
    }
    check = _verifier(FakeIndexes([]), parsed, tmp_path).verify("1", HARRISON_REF)
    assert check.status == ReferenceStatus.UNINDEXED_BY_DESIGN
    assert "not evidence of a problem" in check.explanation


def test_bookish_text_is_detected_without_a_parsed_type(tmp_path):
    """The LLM parse is not always available or correct; the raw string still
    carries the tells ("In:", "(eds)", a publisher name)."""
    parsed = {"title": "Infections with herpes simplex virus", "first_author": "Lerner", "year": 1983}
    check = _verifier(FakeIndexes([]), parsed, tmp_path).verify("1", HARRISON_REF)
    assert check.status == ReferenceStatus.UNINDEXED_BY_DESIGN


def test_unparseable_reference_is_not_an_accusation(tmp_path):
    check = _verifier(FakeIndexes([]), {}, tmp_path).verify("9", "???? garbled ????")
    assert check.status == ReferenceStatus.UNINDEXED_BY_DESIGN


def test_not_found_wording_never_asserts_non_existence(tmp_path):
    """The output is what was observed, not an allegation about the author."""
    v = _verifier(FakeIndexes([]), HEROLD_PARSED, tmp_path)
    check = v.verify("3", HEROLD_REF)
    assert check.status == ReferenceStatus.NOT_FOUND_IN_INDEXES
    text = check.explanation.lower()
    assert "does not prove" in text
    for forbidden in ("fabricat", "hallucinat", "fake", "made up", "invented"):
        assert forbidden not in text


def test_genuine_absence_with_quorum_is_reported(tmp_path):
    """The control is not so strict that the check never fires."""
    check = _verifier(FakeIndexes([]), HEROLD_PARSED, tmp_path).verify("3", HEROLD_REF)
    assert check.status == ReferenceStatus.NOT_FOUND_IN_INDEXES
    assert len(check.indexes_responded) >= 2


# ---------------------------------------------------------------------------
# Retraction
# ---------------------------------------------------------------------------

def test_retraction_is_detected_and_kept_separate_from_existence(tmp_path):
    v = _verifier(FakeIndexes([_match(is_retracted=True)]), HEROLD_PARSED, tmp_path)
    check = v.verify("3", HEROLD_REF)
    assert check.status == ReferenceStatus.VERIFIED       # it exists...
    assert check.retraction_status == RetractionStatus.RETRACTED   # ...and is retracted


def test_expression_of_concern_is_its_own_state(tmp_path):
    rec = _match(is_retracted=None)
    rec.raw["_concern_raised"] = True
    v = _verifier(FakeIndexes([rec]), HEROLD_PARSED, tmp_path)
    assert v.verify("3", HEROLD_REF).retraction_status == RetractionStatus.CONCERN_RAISED


def test_unmatched_reference_has_unknown_retraction_status(tmp_path):
    check = _verifier(FakeIndexes([]), HEROLD_PARSED, tmp_path).verify("3", HEROLD_REF)
    assert check.retraction_status == RetractionStatus.UNKNOWN


# ---------------------------------------------------------------------------
# Cost control
# ---------------------------------------------------------------------------

def test_biomedical_indexes_are_not_queried_when_the_cheap_pair_verifies(tmp_path):
    """253 references times five indexes is rude and slow. Escalate only on a
    miss."""
    indexes = FakeIndexes([_match()])
    _verifier(indexes, HEROLD_PARSED, tmp_path).verify("3", HEROLD_REF)
    assert "europepmc" not in indexes.called
    assert "pubmed" not in indexes.called


def test_repeat_verification_is_served_from_cache(tmp_path):
    indexes = FakeIndexes([_match()])
    v = _verifier(indexes, HEROLD_PARSED, tmp_path)
    v.verify("3", HEROLD_REF)
    calls_after_first = len(indexes.called)
    v.verify("3", HEROLD_REF)
    assert len(indexes.called) == calls_after_first


def test_verify_all_never_raises_on_a_bad_reference(tmp_path):
    class Exploding(FakeIndexes):
        def crossref_bibliographic(self, query):
            raise RuntimeError("boom")

    v = _verifier(Exploding([]), HEROLD_PARSED, tmp_path)
    out = v.verify_all({"1": HEROLD_REF, "2": HARRISON_REF})
    assert set(out) == {"1", "2"}
    assert all(c.status == ReferenceStatus.UNVERIFIED for c in out.values())


# ---------------------------------------------------------------------------
# Similarity helpers
# ---------------------------------------------------------------------------

def test_title_similarity_survives_pdf_extraction_damage():
    mangled = "Glycoprotein C of herpes simplex virus type 1 plays a principal role in the adsorption of virus to cells"
    assert title_similarity(mangled, REAL_TITLE) > 0.95
    assert title_similarity("A study of medieval crop rotation", REAL_TITLE) < 0.5


def test_journal_similarity_handles_abbreviations():
    assert journal_similarity("J Virol", "Journal of Virology") == 1.0
    assert journal_similarity("Proc Natl Acad Sci", "Proceedings of the National Academy of Sciences") == 1.0
    assert journal_similarity("J Virol", "Nature Medicine") < 0.5
