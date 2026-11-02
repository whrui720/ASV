"""Request building and response parsing for ``AcademicPaperFinder``'s own
resolvers — Unpaywall, Semantic Scholar and Crossref — and the end-to-end
union of every resolver in ``find_candidates``.

The one cross-cutting property tested here that no single client can own:
**credentials go only to the host they belong to.** One ``PoliteSession`` talks
to a dozen services and, via ``fetch_with_cookies``, to arbitrary publisher
hosts. A key attached at session level instead of per request would leak to
every one of them.
"""

import pytest

from asv.sourcefinder.academic_paper_finder import AcademicPaperFinder
from asv.sourcefinder.config import CROSSREF_API, SEMANTIC_SCHOLAR_API, UNPAYWALL_API
from asv.sourcefinder.fulltext_apis import (
    ARXIV_QUERY,
    EUROPEPMC_FULLTEXT,
    EUROPEPMC_SEARCH,
    OPENALEX_WORKS,
    PMC_IDCONV,
)

from .api_fakes import load_fixture

pytestmark = pytest.mark.unit

DOI = "10.1371/journal.pmed.0020124"
TITLE = "Why most published research findings are false"
CITATION = "Ioannidis JP. Why most published research findings are false. PLoS Med 2005; 2: e124."
PRINTABLE = ("https://journals.plos.org/plosmedicine/article/file?"
             "id=10.1371/journal.pmed.0020124&type=printable")


class StubLLM:
    """The citation parse is an LLM call; these tests are about what follows it."""

    def __init__(self, parsed):
        self.parsed = parsed
        self.calls = 0

    def call_llm(self, prompt, **kwargs):
        self.calls += 1
        return dict(self.parsed)


PARSED = {"title": TITLE, "first_author": "Ioannidis", "year": 2005, "journal": "PLoS Med"}


def _finder(fake_http, llm=None):
    finder = AcademicPaperFinder(llm_client=llm)
    finder._session = fake_http
    finder.fulltext.http = fake_http
    return finder


@pytest.fixture
def finder(fake_http, creds):
    creds.set(UNPAYWALL_EMAIL="tests@example.org")
    return _finder(fake_http)


def _kinds(cands):
    return [(c.source, c.kind) for c in cands]


# ---------------------------------------------------------------------------
# Unpaywall
# ---------------------------------------------------------------------------

def test_unpaywall_is_skipped_without_an_email(fake_http):
    assert _finder(fake_http)._try_unpaywall(DOI) == []
    assert fake_http.calls == []


def test_unpaywall_request(finder, fake_http):
    fake_http.add(UNPAYWALL_API, fixture="unpaywall.json")

    finder._try_unpaywall(DOI)

    (call,) = fake_http.calls
    assert call.url == f"{UNPAYWALL_API}/{DOI}"
    assert call.params == {"email": "tests@example.org"}


def test_unpaywall_host_type_drives_the_kind(finder, fake_http):
    """Unpaywall knows the PLoS printable PDF is a repository deposit and the
    doi.org link is the publisher's — exactly the distinction ranking needs."""
    fake_http.add(UNPAYWALL_API, fixture="unpaywall.json")

    cands = finder._try_unpaywall(DOI)

    by_url = {}
    for c in cands:
        by_url.setdefault(c.url, c.kind)
    assert by_url[f"https://doi.org/{DOI}"] == "publisher_landing"
    assert by_url[PRINTABLE] == "repository_pdf"
    assert by_url["https://www.ncbi.nlm.nih.gov/pmc/articles/1182327"] == "repository_landing"
    assert all(c.source == "unpaywall" for c in cands)


def test_unpaywall_unknown_doi_is_empty(finder, fake_http):
    fake_http.add(UNPAYWALL_API, {"HTTP_status_code": 404, "error": True}, status=404)

    assert finder._try_unpaywall("10.9999/nope") == []


def test_unpaywall_closed_article_is_empty(finder, fake_http):
    fake_http.add(UNPAYWALL_API, {"doi": DOI, "is_oa": False,
                                  "best_oa_location": None, "oa_locations": []})

    assert finder._try_unpaywall(DOI) == []


# ---------------------------------------------------------------------------
# Semantic Scholar
# ---------------------------------------------------------------------------

S2_PAPER = {"paperId": "abc", "externalIds": {"DOI": DOI},
            "openAccessPdf": {"url": PRINTABLE, "status": "GREEN"}}


def test_s2_by_doi_request_and_parse(finder, fake_http):
    fake_http.add(SEMANTIC_SCHOLAR_API, S2_PAPER)

    cands = finder._try_semantic_scholar_by_doi(DOI)

    (call,) = fake_http.calls
    assert call.url == f"{SEMANTIC_SCHOLAR_API}/paper/DOI:{DOI}"
    assert call.params == {"fields": "openAccessPdf,externalIds"}
    assert call.headers == {}, "no key configured, so no key header"
    assert [c.url for c in cands] == [PRINTABLE]


def test_s2_sends_its_key_when_configured(fake_http, creds):
    creds.set(SEMANTIC_SCHOLAR_API_KEY="s2-key")
    fake_http.add(SEMANTIC_SCHOLAR_API, S2_PAPER)

    _finder(fake_http)._try_semantic_scholar_by_doi(DOI)

    assert fake_http.calls[0].headers == {"x-api-key": "s2-key"}


def test_s2_unknown_doi_is_empty(finder, fake_http):
    # The real answer for this DOI: S2 files the paper under a reprint's DOI.
    fake_http.add(SEMANTIC_SCHOLAR_API,
                  {"error": f"Paper with id DOI:{DOI} not found"}, status=404)

    assert finder._try_semantic_scholar_by_doi(DOI) == []


def test_s2_paper_without_an_open_pdf_is_empty(finder, fake_http):
    fake_http.add(SEMANTIC_SCHOLAR_API, {"paperId": "abc", "openAccessPdf": None})

    assert finder._try_semantic_scholar_by_doi(DOI) == []


def test_s2_search_request(finder, fake_http):
    fake_http.add(SEMANTIC_SCHOLAR_API, fixture="semantic_scholar_search.json")

    finder._try_semantic_scholar_by_text(TITLE, expected_title=TITLE)

    (call,) = fake_http.calls
    assert call.url == f"{SEMANTIC_SCHOLAR_API}/paper/search"
    assert call.params == {"query": TITLE, "fields": "title,openAccessPdf,externalIds",
                           "limit": 3}


def test_s2_search_keeps_matching_rows(finder, fake_http):
    fake_http.add(SEMANTIC_SCHOLAR_API, fixture="semantic_scholar_search.json")

    cands, recovered = finder._try_semantic_scholar_by_text(TITLE, expected_title=TITLE)

    assert recovered is not None
    assert len(cands) == 2


def test_s2_search_rejects_rows_for_a_different_paper(finder, fake_http):
    fake_http.add(SEMANTIC_SCHOLAR_API, fixture="semantic_scholar_search.json")

    cands, recovered = finder._try_semantic_scholar_by_text(
        "Oncolytic herpes simplex virus vectors for glioma",
        expected_title="Oncolytic herpes simplex virus vectors for glioma",
    )

    assert cands == [] and recovered is None


def test_s2_search_skips_text_too_short_to_search(finder, fake_http):
    assert finder._try_semantic_scholar_by_text("short") == ([], None)
    assert fake_http.calls == []


# ---------------------------------------------------------------------------
# Crossref
# ---------------------------------------------------------------------------

def test_crossref_takes_only_pdf_links(finder, fake_http):
    body = load_fixture("crossref_work.json")
    body["message"]["link"] = [
        {"URL": "https://journals.plos.org/x.pdf", "content-type": "application/pdf"},
        {"URL": "https://journals.plos.org/x.xml", "content-type": "application/xml"},
        {"URL": "https://journals.plos.org/file?type=printable&fmt=pdf",
         "content-type": "unspecified"},
    ]
    fake_http.add(CROSSREF_API, body)

    cands = finder._try_crossref(DOI)

    assert fake_http.calls[0].url == f"{CROSSREF_API}/{DOI}"
    assert [c.url for c in cands] == [
        "https://journals.plos.org/x.pdf",
        "https://journals.plos.org/file?type=printable&fmt=pdf",
    ]


def test_crossref_does_not_emit_the_landing_url(finder, fake_http):
    """``message.URL`` is appended once, last, by ``find_candidates`` so it can
    never displace a repository mirror."""
    fake_http.add(CROSSREF_API, fixture="crossref_work.json")

    assert finder._try_crossref(DOI) == []


def test_crossref_bibliographic_sends_structured_fields(finder, fake_http):
    fake_http.add(CROSSREF_API, fixture="crossref_bibliographic.json")

    finder._resolve_doi_via_crossref(PARSED, CITATION)

    params = fake_http.calls[0].params
    assert params["query.bibliographic"] == TITLE
    assert params["query.author"] == "Ioannidis"
    assert params["query.container-title"] == "PLoS Med"
    assert params["mailto"] == "tests@example.org"


def test_crossref_bibliographic_skips_a_mismatched_top_hit(finder, fake_http):
    body = load_fixture("crossref_bibliographic.json")
    body["message"]["items"][0]["title"] = ["Machine learning approaches to protein folding"]
    fake_http.add(CROSSREF_API, body)

    assert finder._resolve_doi_via_crossref(PARSED, CITATION) == DOI


@pytest.mark.xfail(strict=True, reason=(
    "Known gap: title_matches accepts 'Why most PRE-published research findings "
    "are false' (OSF, 2020) for Ioannidis 2005 — Jaccard 7/8. This is the real "
    "top Crossref hit for the bare title. The resolver does not check year or "
    "author on the hit; the reference audit does, via its own scoring."
))
def test_crossref_bibliographic_rejects_a_near_title_from_another_paper(finder, fake_http):
    fake_http.add(CROSSREF_API, fixture="crossref_bibliographic.json")

    assert finder._resolve_doi_via_crossref(PARSED, CITATION) == DOI


def test_crossref_bibliographic_without_a_title_uses_the_raw_string(finder, fake_http):
    fake_http.add(CROSSREF_API, fixture="crossref_bibliographic.json")

    finder._resolve_doi_via_crossref({}, CITATION)

    assert fake_http.calls[0].params["query.bibliographic"] == CITATION[:200]
    assert "query.author" not in fake_http.calls[0].params


# ---------------------------------------------------------------------------
# find_candidates — every resolver, unioned and ranked
# ---------------------------------------------------------------------------

def _all_routes(fake_http):
    fake_http.add(EUROPEPMC_SEARCH, fixture="europepmc_search.json")
    fake_http.add(OPENALEX_WORKS, fixture="openalex_works.json")
    fake_http.add(UNPAYWALL_API, fixture="unpaywall.json")
    fake_http.add(SEMANTIC_SCHOLAR_API, S2_PAPER)
    fake_http.add(CROSSREF_API, fixture="crossref_work.json")
    fake_http.add(PMC_IDCONV, fixture="pmc_idconv.json")
    fake_http.add("https://api.core.ac.uk", {"results": []})


def test_find_candidates_ranks_the_union(fake_http, creds):
    creds.set(UNPAYWALL_EMAIL="tests@example.org")
    _all_routes(fake_http)
    finder = _finder(fake_http, StubLLM(PARSED))

    cands = finder.find_candidates(CITATION)

    assert cands[0].url == EUROPEPMC_FULLTEXT.format(pmcid="PMC1182327")
    ranks = [c.rank for c in cands]
    assert ranks == sorted(ranks), "candidates must come back in kind order"
    assert len({c.url for c in cands}) == len(cands), "no duplicate URLs"
    # Every resolver is asked even after an earlier one answered (F1). Their
    # answers overlap — the same PLoS PDF comes back from OpenAlex, Unpaywall
    # and S2 — so surviving sources are fewer than resolvers asked.
    for endpoint in (EUROPEPMC_SEARCH, OPENALEX_WORKS, UNPAYWALL_API,
                     SEMANTIC_SCHOLAR_API, CROSSREF_API):
        assert fake_http.calls_to(endpoint), f"{endpoint} was never asked"
    assert cands[-1].url == f"https://doi.org/{DOI}", "the DOI landing page ranks last"


def test_find_candidates_recovers_a_doi_for_the_doi_keyed_resolvers(fake_http, creds):
    """The citation carries no DOI. Europe PMC recovers it from the title, and
    Unpaywall/S2/Crossref — all DOI-keyed — are then asked with it."""
    creds.set(UNPAYWALL_EMAIL="tests@example.org")
    _all_routes(fake_http)

    _finder(fake_http, StubLLM(PARSED)).find_candidates(CITATION)

    assert fake_http.calls_to(UNPAYWALL_API)[0].url.endswith(DOI)
    assert fake_http.calls_to(CROSSREF_API)[0].url.endswith(DOI)
    assert fake_http.calls_to(f"{SEMANTIC_SCHOLAR_API}/paper/DOI:{DOI}")


def test_find_candidates_is_cached_per_citation(fake_http, creds):
    creds.set(UNPAYWALL_EMAIL="tests@example.org")
    _all_routes(fake_http)
    llm = StubLLM(PARSED)
    finder = _finder(fake_http, llm)

    first = finder.find_candidates(CITATION)
    n_calls = len(fake_http.calls)
    second = finder.find_candidates(CITATION)

    assert first == second
    assert len(fake_http.calls) == n_calls, "a repeat lookup must not touch the network"
    assert llm.calls == 1


def test_find_candidates_records_resolved_hosts(fake_http, creds):
    creds.set(UNPAYWALL_EMAIL="tests@example.org")
    _all_routes(fake_http)
    finder = _finder(fake_http, StubLLM(PARSED))

    finder.find_candidates(CITATION)

    assert "www.ebi.ac.uk" in finder.resolved_hosts
    assert "journals.plos.org" in finder.resolved_hosts


def test_find_candidates_with_nothing_found_is_empty(fake_http, creds):
    creds.set(UNPAYWALL_EMAIL="tests@example.org")
    fake_http.add(EUROPEPMC_SEARCH, {"resultList": {"result": []}})
    fake_http.add(OPENALEX_WORKS, {"results": []})
    fake_http.add(SEMANTIC_SCHOLAR_API, {"total": 0, "data": []})
    fake_http.add(CROSSREF_API, {"message": {"items": []}})
    fake_http.add(ARXIV_QUERY, "<feed></feed>")

    assert _finder(fake_http, StubLLM(PARSED)).find_candidates(CITATION) == []


def test_keys_reach_only_their_own_host(fake_http, creds):
    creds.set(
        UNPAYWALL_EMAIL="tests@example.org",
        SEMANTIC_SCHOLAR_API_KEY="s2-secret",
        CORE_API_KEY="core-secret",
    )
    _all_routes(fake_http)
    fake_http.add(ARXIV_QUERY, "<feed></feed>")
    finder = _finder(fake_http, StubLLM(PARSED))

    finder.find_candidates(CITATION)
    # A second, DOI-less citation, so the title-search paths run too.
    finder.find_candidates("Unknown A. Some unindexed report title here. 1999.")

    assert fake_http.calls, "sanity: the resolvers ran"
    for call in fake_http.calls:
        blob = repr(call.headers) + repr(call.params) + call.url
        if "s2-secret" in blob:
            assert call.url.startswith(SEMANTIC_SCHOLAR_API), call.url
        if "core-secret" in blob:
            assert call.url.startswith("https://api.core.ac.uk"), call.url
