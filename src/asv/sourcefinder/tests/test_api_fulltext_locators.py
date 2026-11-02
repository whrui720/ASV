"""Request building and response parsing for the full-text locators.

``test_resolution_breadth.py`` pins how candidates are *ranked*. This module
pins how each locator *produces* them from a real API response: which fields
become URLs, which kind each URL is assigned, and which requests are never
made at all because the credential that would make them succeed is absent.

That last one is a real property, not a nicety. A candidate slot spent on a
guaranteed 400 is a slot the repository mirror does not get, and an OpenAlex
call without a contact address stalls ~90s on the anonymous pool.
"""

import pytest
import requests

from asv.sourcefinder.fulltext_apis import (
    ARXIV_QUERY,
    CORE_SEARCH,
    EUROPEPMC_FULLTEXT,
    EUROPEPMC_SEARCH,
    NCBI_EFETCH,
    OPENALEX_WORKS,
    PMC_IDCONV,
    FullTextAPIs,
)

from .api_fakes import load_fixture

pytestmark = pytest.mark.unit

DOI = "10.1371/journal.pmed.0020124"
TITLE = "Why most published research findings are false"
PMC_XML = EUROPEPMC_FULLTEXT.format(pmcid="PMC1182327")


@pytest.fixture
def api(fake_http, creds):
    creds.set(UNPAYWALL_EMAIL="tests@example.org")
    return FullTextAPIs(session=fake_http)


@pytest.fixture
def anonymous_api(fake_http):
    return FullTextAPIs(session=fake_http)


def _kinds(cands):
    return [(c.source, c.kind) for c in cands]


# ---------------------------------------------------------------------------
# Europe PMC
# ---------------------------------------------------------------------------

def test_europepmc_by_doi_returns_both_jats_routes(api, fake_http):
    fake_http.add(EUROPEPMC_SEARCH, fixture="europepmc_search.json")

    cands, meta = api.europepmc(doi=DOI)

    (call,) = fake_http.calls
    assert call.params["query"] == f'DOI:"{DOI}"'
    assert call.params["resultType"] == "core"
    assert call.params["pageSize"] == 1
    assert cands[0].url == PMC_XML
    assert _kinds(cands) == [
        ("europepmc_fulltext", "fulltext_xml"), ("pmc_efetch", "fulltext_xml"),
    ]
    assert meta == {"doi": DOI, "pmid": "16060722", "pmcid": "PMC1182327",
                    "title": "Why most published research findings are false."}


def test_europepmc_skips_its_own_website_and_subscription_links(api, fake_http):
    """The fixture's fullTextUrlList is real: one subscription DOI link and two
    europepmc.org links (Cloudflare-walled). None of them may become a
    candidate — the REST mirror already covers the article."""
    fake_http.add(EUROPEPMC_SEARCH, fixture="europepmc_search.json")

    cands, _ = api.europepmc(doi=DOI)

    assert not any("europepmc.org" in c.url for c in cands)
    assert not any(c.url == f"https://doi.org/{DOI}" for c in cands)


def test_europepmc_keeps_open_access_links_on_other_hosts(api, fake_http):
    body = load_fixture("europepmc_search.json")
    body["resultList"]["result"][0]["fullTextUrlList"]["fullTextUrl"].append({
        "availabilityCode": "OA", "documentStyle": "pdf", "site": "PubMedCentral",
        "url": "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC1182327/pdf/x.pdf",
    })
    fake_http.add(EUROPEPMC_SEARCH, body)

    cands, _ = api.europepmc(doi=DOI)

    assert ("europepmc", "repository_pdf") in _kinds(cands)


def test_europepmc_does_not_offer_jats_it_does_not_hold(api, fake_http):
    """``inEPMC: N`` means fullTextXML answers 500. Offering it anyway wastes a
    candidate slot and reads as a server fault."""
    body = load_fixture("europepmc_search.json")
    body["resultList"]["result"][0]["inEPMC"] = "N"
    fake_http.add(EUROPEPMC_SEARCH, body)

    cands, _ = api.europepmc(doi=DOI)

    assert _kinds(cands) == [("pmc_efetch", "fulltext_xml")]


def test_europepmc_title_search_is_fielded(api, fake_http):
    fake_http.add(EUROPEPMC_SEARCH, fixture="europepmc_search.json")

    api.europepmc(title='Why most "published" research findings are false',
                  first_author="Ioannidis", year=2005)

    query = fake_http.calls[0].params["query"]
    assert query == (
        'TITLE:"Why most published research findings are false" '
        'AND AUTH:"Ioannidis" AND PUB_YEAR:2005'
    )
    assert fake_http.calls[0].params["pageSize"] == 3


def test_europepmc_title_search_rejects_a_different_paper(api, fake_http):
    """A title search always returns its best row. Accepting it unchecked is
    how a claim gets judged against the wrong paper."""
    fake_http.add(EUROPEPMC_SEARCH, fixture="europepmc_search.json")

    cands, meta = api.europepmc(title="Oncolytic herpes simplex virus vectors for glioma")

    assert cands == [] and meta == {}


def test_europepmc_falls_back_from_doi_to_title(api, fake_http):
    fake_http.add(EUROPEPMC_SEARCH, {"resultList": {"result": []}},
                  params=lambda p: p["query"].startswith("DOI:"))
    fake_http.add(EUROPEPMC_SEARCH, fixture="europepmc_search.json")

    cands, _ = api.europepmc(doi=DOI, title=TITLE)

    assert [c.params["query"][:5] for c in fake_http.calls] == ["DOI:\"", "TITLE"]
    assert cands


def test_europepmc_error_is_empty_not_raised(api, fake_http):
    fake_http.add(EUROPEPMC_SEARCH, "", status=500)

    assert api.europepmc(doi=DOI) == ([], {})


# ---------------------------------------------------------------------------
# PMC routes and the ID converter
# ---------------------------------------------------------------------------

def test_pmc_fulltext_normalises_a_bare_number(api):
    cands = api.pmc_fulltext("1182327")

    assert cands[0].url == PMC_XML
    assert cands[1].url == NCBI_EFETCH + "?db=pmc&id=1182327&retmode=xml"


def test_pmc_efetch_carries_the_ncbi_key_when_set(api, creds):
    creds.set(PUBMED_API_KEY="pm key")

    efetch = api.pmc_fulltext("PMC1182327")[-1]

    assert efetch.url.endswith("&api_key=pm%20key")


def test_pmc_fulltext_with_no_id_is_empty(api):
    assert api.pmc_fulltext("  ") == []


def test_idconv_maps_doi_to_pmcid(api, fake_http):
    fake_http.add(PMC_IDCONV, fixture="pmc_idconv.json")

    assert api.pmcid_for_doi(DOI) == "PMC1182327"
    assert fake_http.calls[0].params == {
        "ids": DOI, "format": "json", "tool": "asv", "email": "tests@example.org",
    }


def test_idconv_without_a_deposit_is_none(api, fake_http):
    fake_http.add(PMC_IDCONV, {"status": "ok", "records": [
        {"doi": DOI, "requested-id": DOI, "status": "error", "errmsg": "invalid article id"},
    ]})

    assert api.pmcid_for_doi(DOI) is None


def test_idconv_rate_limit_is_none(api, fake_http):
    fake_http.add(PMC_IDCONV, "<title>429</title>", status=429)

    assert api.pmcid_for_doi(DOI) is None


# ---------------------------------------------------------------------------
# OpenAlex
# ---------------------------------------------------------------------------

def test_openalex_is_skipped_without_a_contact_email(anonymous_api, fake_http):
    assert anonymous_api.openalex(doi=DOI) == ([], None)
    assert fake_http.calls == []


def test_openalex_turns_locations_into_ranked_kinds(api, fake_http):
    fake_http.add(OPENALEX_WORKS, fixture="openalex_works.json")

    cands, recovered = api.openalex(doi=DOI)

    assert fake_http.calls[0].params == {
        "per-page": 3, "mailto": "tests@example.org", "filter": f"doi:{DOI}",
    }
    assert recovered == DOI
    by_url = {c.url: c.kind for c in cands}
    printable = ("https://journals.plos.org/plosmedicine/article/file?"
                 "id=10.1371/journal.pmed.0020124&type=printable")
    assert by_url[printable] == "repository_pdf"
    assert by_url[f"https://doi.org/{DOI}"] == "publisher_landing"
    assert by_url["https://www.ncbi.nlm.nih.gov/pmc/articles/1182327"] == "repository_landing"


def test_openalex_drops_closed_landing_pages(api, fake_http):
    """The fixture's PubMed location is ``is_oa: false`` — a page we already
    know cannot contain the full text."""
    fake_http.add(OPENALEX_WORKS, fixture="openalex_works.json")

    cands, _ = api.openalex(doi=DOI)

    assert not any("pubmed.ncbi.nlm.nih.gov" in c.url for c in cands)


def test_openalex_pmcid_adds_jats_routes(api, fake_http):
    body = load_fixture("openalex_works.json")
    body["results"][0]["ids"]["pmcid"] = "https://www.ncbi.nlm.nih.gov/pmc/articles/1182327"
    fake_http.add(OPENALEX_WORKS, body)

    cands, _ = api.openalex(doi=DOI)

    assert ("europepmc_fulltext", "fulltext_xml") in _kinds(cands)
    assert any(c.url == PMC_XML for c in cands)


def test_openalex_title_search_rejects_a_different_paper(api, fake_http):
    fake_http.add(OPENALEX_WORKS, fixture="openalex_works.json")

    assert api.openalex(title="Oncolytic herpes simplex virus vectors for glioma") == ([], None)
    assert fake_http.calls[0].params["filter"].startswith("title.search:")


def test_openalex_needs_a_doi_or_title(api, fake_http):
    assert api.openalex() == ([], None)
    assert fake_http.calls == []


# ---------------------------------------------------------------------------
# CORE
# ---------------------------------------------------------------------------

CORE_HIT = {"results": [
    {"id": 1, "title": TITLE, "downloadUrl": "https://core.ac.uk/download/pdf/123.pdf"},
    {"id": 2, "title": TITLE, "downloadUrl": "https://core.ac.uk/reader/456"},
    {"id": 3, "title": TITLE, "downloadUrl": None},
]}


def test_core_is_skipped_without_a_key(api, fake_http):
    assert api.core(TITLE, doi=DOI) == []
    assert fake_http.calls == []


def test_core_authenticates_with_a_bearer_header(api, fake_http, creds):
    creds.set(CORE_API_KEY="core-key")
    fake_http.add(CORE_SEARCH, CORE_HIT)

    api.core(TITLE)

    call = fake_http.calls[0]
    assert call.headers == {"Authorization": "Bearer core-key"}
    assert "core-key" not in str(call.params)


def test_core_tries_the_doi_before_the_title(api, fake_http, creds):
    creds.set(CORE_API_KEY="core-key")
    fake_http.add(CORE_SEARCH, {"results": []}, params=lambda p: p["q"].startswith("doi:"))
    fake_http.add(CORE_SEARCH, CORE_HIT)

    cands = api.core(TITLE, doi=DOI)

    assert [c.params["q"] for c in fake_http.calls] == [f'doi:"{DOI}"', TITLE]
    assert _kinds(cands) == [("core", "repository_pdf"), ("core", "repository_landing")]


def test_core_stops_after_the_first_query_that_answers(api, fake_http, creds):
    creds.set(CORE_API_KEY="core-key")
    fake_http.add(CORE_SEARCH, CORE_HIT)

    api.core(TITLE, doi=DOI)

    assert len(fake_http.calls) == 1


# ---------------------------------------------------------------------------
# arXiv
# ---------------------------------------------------------------------------

def test_arxiv_parses_the_atom_feed(api, fake_http):
    fake_http.add(ARXIV_QUERY, fixture="arxiv_query.xml")

    cands = api.arxiv('Attention is all "you" need')

    assert fake_http.calls[0].params == {
        "search_query": 'ti:"Attention is all you need"', "max_results": 2,
    }
    assert [c.url for c in cands] == ["https://arxiv.org/pdf/1706.03762v7"]
    assert _kinds(cands) == [("arxiv", "repository_pdf")]


def test_arxiv_ignores_the_feed_id(api, fake_http):
    """The feed's own ``<id>`` is an arxiv.org/api URL, not a paper."""
    fake_http.add(ARXIV_QUERY, fixture="arxiv_query.xml")

    assert not any("/api/" in c.url for c in api.arxiv("Attention is all you need"))


def test_arxiv_skips_titles_too_short_to_search(api, fake_http):
    assert api.arxiv("Short") == []
    assert fake_http.calls == []


# ---------------------------------------------------------------------------
# Tier 2 publisher TDM
# ---------------------------------------------------------------------------

def test_tdm_is_silent_without_keys(api):
    assert api.publisher_tdm(DOI) == []


@pytest.mark.parametrize("key,source,kind", [
    ("WILEY_TDM_TOKEN", "wiley_tdm", "publisher_pdf"),
    ("ELSEVIER_API_KEY", "elsevier_tdm", "fulltext_xml"),
    ("SPRINGER_API_KEY", "springer_oa", "fulltext_xml"),
])
def test_each_tdm_endpoint_needs_only_its_own_key(api, creds, key, source, kind):
    creds.set(**{key: "k"})

    assert _kinds(api.publisher_tdm(DOI)) == [(source, kind)]


def test_only_springer_puts_its_key_in_the_url(api, creds):
    """Wiley and Elsevier authenticate by header (``credentials.auth_headers_for``),
    so their keys must not appear in a URL that ends up in the manifest."""
    creds.set(WILEY_TDM_TOKEN="wiley-secret", ELSEVIER_API_KEY="els-secret",
              SPRINGER_API_KEY="springer-key")

    urls = [c.url for c in api.publisher_tdm(DOI)]

    assert not any("wiley-secret" in u or "els-secret" in u for u in urls)
    assert any("api_key=springer-key" in u for u in urls)


# ---------------------------------------------------------------------------
# locate() — the chaining between locators
# ---------------------------------------------------------------------------

def test_locate_carries_a_recovered_doi_into_openalex(api, fake_http):
    """Title in, DOI out of Europe PMC, DOI into OpenAlex. The ID converter is
    not asked because Europe PMC already supplied the PMCID."""
    fake_http.add(EUROPEPMC_SEARCH, fixture="europepmc_search.json")
    fake_http.add(OPENALEX_WORKS, fixture="openalex_works.json")

    cands, meta = api.locate(title=TITLE, first_author="Ioannidis", year=2005)

    assert fake_http.calls_to(OPENALEX_WORKS)[0].params["filter"] == f"doi:{DOI}"
    assert not fake_http.calls_to(PMC_IDCONV)
    assert not fake_http.calls_to(ARXIV_QUERY), "arXiv is a last resort only"
    assert meta["pmcid"] == "PMC1182327"
    assert any(c.url == PMC_XML for c in cands)


def test_locate_asks_the_id_converter_when_no_pmcid_is_known(api, fake_http):
    fake_http.add(EUROPEPMC_SEARCH, {"resultList": {"result": []}})
    fake_http.add(OPENALEX_WORKS, fixture="openalex_works.json")
    fake_http.add(PMC_IDCONV, fixture="pmc_idconv.json")

    cands, meta = api.locate(doi=f"https://doi.org/{DOI}")

    assert fake_http.calls_to(PMC_IDCONV)[0].params["ids"] == DOI, "DOI must be cleaned first"
    assert meta["pmcid"] == "PMC1182327"
    assert any(c.url == PMC_XML for c in cands)


def test_locate_reaches_arxiv_only_when_nothing_else_answered(api, fake_http):
    fake_http.add(EUROPEPMC_SEARCH, {"resultList": {"result": []}})
    fake_http.add(OPENALEX_WORKS, {"results": []})
    fake_http.add(ARXIV_QUERY, fixture="arxiv_query.xml")

    cands, _ = api.locate(title="Attention is all you need")

    assert _kinds(cands) == [("arxiv", "repository_pdf")]


def test_locate_survives_every_locator_failing(api, fake_http):
    fake_http.add(EUROPEPMC_SEARCH, raises=requests.ConnectionError("down"))
    fake_http.add(OPENALEX_WORKS, "", status=503)
    fake_http.add(PMC_IDCONV, "", status=429)

    assert api.locate(doi=DOI) == ([], {})
