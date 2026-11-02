"""Request building and response parsing for the bibliographic index clients.

``test_reference_verifier.py`` tests the *decisions* the audit makes, over a
``FakeIndexes`` that hands it ``IndexRecord`` objects directly. This module
tests the layer underneath: that each client asks its index the right question
and turns the real response shape into the right ``IndexRecord``.

The property that matters most here is ``responded``. "The index answered and
had no match" is evidence toward *reference not found*; "the index did not
answer" is not. Confusing the two turns an API outage into an allegation of
fabrication, so every client's error paths are pinned below.

Payloads are real responses (``fixtures/api/``) for Ioannidis 2005, *Why most
published research findings are false*, PLoS Med 2(8): e124.
"""

import pytest
import requests

from asv.sourcefinder import index_clients
from asv.sourcefinder.index_clients import BibliographicIndexes, _surname

from .api_fakes import load_fixture

pytestmark = pytest.mark.unit

DOI = "10.1371/journal.pmed.0020124"
EMAIL = "tests@example.org"

CROSSREF = "https://api.crossref.org/works"
OPENALEX = "https://api.openalex.org/works"
EUROPEPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
ECITMATCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/ecitmatch.cgi"
ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
ESUMMARY = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
DATACITE = "https://api.datacite.org/dois"


@pytest.fixture
def indexes(fake_http):
    idx = BibliographicIndexes(contact_email=EMAIL)
    idx._http = fake_http
    return idx


# ---------------------------------------------------------------------------
# Author-name parsing — shared by every index
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ({"given": "John P. A.", "family": "Ioannidis"}, "Ioannidis"),          # Crossref
    ({"display_name": "John P. A. Ioannidis"}, "Ioannidis"),                # OpenAlex
    ({"lastName": "Ioannidis", "initials": "JP"}, "Ioannidis"),             # Europe PMC
    ({"name": "Ioannidis JP", "authtype": "Author"}, "Ioannidis"),          # PubMed esummary
    ({"name": "Blasco Navarro, Javier"}, "Blasco Navarro"),                 # DataCite, no familyName
    ({"familyName": "Blasco Navarro", "name": "x"}, "Blasco Navarro"),      # DataCite
    ("Ioannidis JP.", "Ioannidis"),                                         # Europe PMC authorString
    ("Smith, A. B.", "Smith"),
    ("van der Berg JP", "van der Berg"),
    ("Wei Li", "Li"),                                                       # "Li" is a surname, not initials
    ({}, None),
    ("   ", None),
    (None, None),
])
def test_surname_handles_every_index_shape(raw, expected):
    assert _surname(raw) == expected


def test_pubmed_authors_are_surnames_not_initials():
    """The bug this was written for: esummary returns ``{"name": "Ioannidis JP"}``
    and the last-token rule produced ``"JP"`` — so no PubMed hit could ever
    corroborate a match on author."""
    node = load_fixture("pubmed_esummary.json")["result"]["16060722"]
    assert [_surname(a) for a in node["authors"]] == ["Ioannidis"]


# ---------------------------------------------------------------------------
# Crossref
# ---------------------------------------------------------------------------

def test_crossref_by_doi_builds_the_request(indexes, fake_http):
    fake_http.add(f"{CROSSREF}/{DOI}", fixture="crossref_work.json")

    indexes.crossref_by_doi(DOI)

    (call,) = fake_http.calls
    assert call.url == f"{CROSSREF}/{DOI}"
    assert call.params == {"mailto": EMAIL}


def test_crossref_by_doi_parses_the_record(indexes, fake_http):
    fake_http.add(f"{CROSSREF}/{DOI}", fixture="crossref_work.json")

    resp = indexes.crossref_by_doi(DOI)

    assert resp.responded and resp.index == "crossref"
    (rec,) = resp.records
    assert rec.title == "Why Most Published Research Findings Are False"
    assert rec.authors == ["Ioannidis"]
    assert rec.year == 2005
    assert rec.doi == DOI
    assert rec.container == "PLoS Medicine"
    assert rec.work_type == "journal-article"
    assert rec.url == f"https://doi.org/{DOI}"
    assert rec.is_retracted is None


def test_crossref_reads_retraction_from_update_to(indexes, fake_http):
    body = load_fixture("crossref_work.json")
    body["message"]["update-to"] = [{
        "type": "retraction", "DOI": "10.1371/x.retraction",
        "URL": "https://doi.org/10.1371/x.retraction",
    }]
    fake_http.add(f"{CROSSREF}/{DOI}", body)

    (rec,) = indexes.crossref_by_doi(DOI).records

    assert rec.is_retracted is True
    assert rec.retraction_notice_url == "https://doi.org/10.1371/x.retraction"


def test_crossref_unknown_doi_is_an_answer(indexes, fake_http):
    fake_http.add(CROSSREF, {"status": "error"}, status=404)

    resp = indexes.crossref_by_doi("10.9999/nope")

    assert resp.responded is True
    assert resp.records == []


@pytest.mark.parametrize("status", [500, 503, 429])
def test_crossref_server_error_is_not_an_answer(indexes, fake_http, status):
    fake_http.add(CROSSREF, "", status=status)

    resp = indexes.crossref_by_doi(DOI)

    assert resp.responded is False
    assert resp.error


def test_crossref_connection_error_is_not_an_answer(indexes, fake_http):
    fake_http.add(CROSSREF, raises=requests.ConnectionError("reset"))

    resp = indexes.crossref_by_doi(DOI)

    assert resp.responded is False
    assert "reset" in resp.error


def test_crossref_bibliographic_asks_for_retraction_fields(indexes, fake_http):
    fake_http.add(CROSSREF, fixture="crossref_bibliographic.json")

    resp = indexes.crossref_bibliographic("Why most published research findings are false")

    (call,) = fake_http.calls
    assert call.params["query.bibliographic"] == "Why most published research findings are false"
    assert call.params["rows"] == index_clients.REFCHECK_MAX_CANDIDATES
    # Without update-to in the select list the retraction check is blind.
    assert "update-to" in call.params["select"].split(",")
    assert [r.doi for r in resp.records] == ["10.31219/osf.io/29jnp", DOI]


def test_crossref_bibliographic_truncates_long_queries(indexes, fake_http):
    fake_http.add(CROSSREF, fixture="crossref_bibliographic.json")

    indexes.crossref_bibliographic("x" * 2000)

    assert len(fake_http.calls[0].params["query.bibliographic"]) == 400


def test_crossref_bibliographic_bad_request_is_an_answer(indexes, fake_http):
    fake_http.add(CROSSREF, {"status": "failed"}, status=400)

    resp = indexes.crossref_bibliographic("((")

    assert resp.responded is True and resp.records == []


def test_no_mailto_without_a_contact_email(fake_http):
    idx = BibliographicIndexes(contact_email="")
    idx._http = fake_http
    fake_http.add(CROSSREF, fixture="crossref_work.json")

    idx.crossref_by_doi(DOI)

    assert "mailto" not in fake_http.calls[0].params


# ---------------------------------------------------------------------------
# OpenAlex
# ---------------------------------------------------------------------------

def test_openalex_by_doi_parses_the_record(indexes, fake_http):
    fake_http.add(OPENALEX, fixture="openalex_works.json")

    resp = indexes.openalex_by_doi(DOI)

    (call,) = fake_http.calls
    assert call.params == {"mailto": EMAIL, "filter": f"doi:{DOI}", "per-page": 1}
    (rec,) = resp.records
    assert rec.title == "Why Most Published Research Findings Are False"
    assert rec.authors == ["Ioannidis"]
    assert rec.year == 2005
    assert rec.doi == DOI, "the https://doi.org/ prefix must be stripped"
    assert rec.pmid == "16060722", "the pubmed URL must be reduced to the bare id"
    assert rec.container == "PLoS Medicine"
    assert rec.is_retracted is False


def test_openalex_title_search_falls_back_to_fulltext_search(indexes, fake_http):
    fake_http.add(OPENALEX, {"results": []},
                  params=lambda p: str(p.get("filter", "")).startswith("title.search:"))
    fake_http.add(OPENALEX, fixture="openalex_works.json", params={"search": "Why most"})

    resp = indexes.openalex_by_title("Why most")

    assert [c.params.get("filter") or c.params.get("search") for c in fake_http.calls] == [
        "title.search:Why most", "Why most",
    ]
    assert len(resp.records) == 1


def test_openalex_title_search_hit_skips_the_fallback(indexes, fake_http):
    fake_http.add(OPENALEX, fixture="openalex_works.json")

    indexes.openalex_by_title("Why most published research findings are false")

    assert len(fake_http.calls) == 1


def test_openalex_outage_is_not_an_answer(indexes, fake_http):
    fake_http.add(OPENALEX, "", status=502)

    assert indexes.openalex_by_doi(DOI).responded is False


def test_openalex_tolerates_missing_optional_fields(indexes, fake_http):
    fake_http.add(OPENALEX, {"results": [{"display_name": "Bare work"}]})

    (rec,) = indexes.openalex_by_doi(DOI).records

    assert rec.title == "Bare work"
    assert rec.doi is None and rec.pmid is None and rec.authors == []


# ---------------------------------------------------------------------------
# Europe PMC
# ---------------------------------------------------------------------------

def test_europepmc_builds_a_core_query(indexes, fake_http):
    fake_http.add(EUROPEPMC, fixture="europepmc_search.json")

    indexes.europepmc(f'DOI:"{DOI}"')

    (call,) = fake_http.calls
    assert call.params["query"] == f'DOI:"{DOI}"'
    assert call.params["format"] == "json"
    assert call.params["resultType"] == "core"


def test_europepmc_parses_the_record(indexes, fake_http):
    fake_http.add(EUROPEPMC, fixture="europepmc_search.json")

    (rec,) = indexes.europepmc("q").records

    assert rec.title == "Why most published research findings are false."
    assert rec.authors == ["Ioannidis"]
    assert rec.year == 2005
    assert rec.doi == DOI
    assert rec.pmid == "16060722"
    assert rec.url == f"https://doi.org/{DOI}"
    assert rec.is_retracted is None


def test_europepmc_journal_comes_from_journal_info(indexes, fake_http):
    """The bug this was written for: core results carry no ``journalTitle``, so
    ``container`` was always None and journal corroboration scored zero for
    every Europe PMC hit."""
    fake_http.add(EUROPEPMC, fixture="europepmc_search.json")

    (rec,) = indexes.europepmc("q").records

    assert rec.container == "PLoS medicine"


def test_europepmc_falls_back_to_author_string(indexes, fake_http):
    body = load_fixture("europepmc_search.json")
    rec = body["resultList"]["result"][0]
    del rec["authorList"]
    rec["authorString"] = "Ioannidis JP, Smith AB."
    fake_http.add(EUROPEPMC, body)

    (parsed,) = indexes.europepmc("q").records

    assert parsed.authors == ["Ioannidis", "Smith"]


def test_europepmc_flags_retraction_and_concern(indexes, fake_http):
    body = load_fixture("europepmc_search.json")
    body["resultList"]["result"][0]["pubTypeList"] = {
        "pubType": ["Journal Article", "Retracted Publication", "Expression of Concern"],
    }
    fake_http.add(EUROPEPMC, body)

    (rec,) = indexes.europepmc("q").records

    assert rec.is_retracted is True
    assert rec.raw["_concern_raised"] is True


def test_europepmc_bad_year_is_dropped_not_raised(indexes, fake_http):
    body = load_fixture("europepmc_search.json")
    body["resultList"]["result"][0]["pubYear"] = "in press"
    fake_http.add(EUROPEPMC, body)

    (rec,) = indexes.europepmc("q").records

    assert rec.year is None


def test_europepmc_outage_is_not_an_answer(indexes, fake_http):
    fake_http.add(EUROPEPMC, raises=requests.Timeout("slow"))

    assert indexes.europepmc("q").responded is False


# ---------------------------------------------------------------------------
# PubMed
# ---------------------------------------------------------------------------

def _pubmed_routes(fake_http):
    fake_http.add(ECITMATCH, fixture="pubmed_ecitmatch.txt")
    fake_http.add(ESEARCH, fixture="pubmed_esearch.json")
    fake_http.add(ESUMMARY, fixture="pubmed_esummary.json", params={"id": "16060722"})


def test_ecitmatch_sends_a_pipe_delimited_citation(indexes, fake_http):
    _pubmed_routes(fake_http)

    indexes.pubmed_ecitmatch(
        journal="PLoS Med", year=2005, volume="2", first_page="e124",
        author="Ioannidis JP", key="ref1",
    )

    ecit = fake_http.calls_to(ECITMATCH)[0]
    assert ecit.params["bdata"] == "PLoS Med|2005|2|e124|Ioannidis JP|ref1|"
    assert ecit.params["db"] == "pubmed"
    assert "api_key" not in ecit.params


def test_ecitmatch_hit_is_resolved_through_esummary(indexes, fake_http):
    _pubmed_routes(fake_http)

    resp = indexes.pubmed_ecitmatch(
        journal="PLoS Med", year=2005, volume="2", first_page="e124",
        author="Ioannidis JP", key="ref1",
    )

    assert resp.responded
    (rec,) = resp.records
    assert rec.pmid == "16060722"
    assert rec.doi == DOI, "DOI must be read out of articleids"
    assert rec.authors == ["Ioannidis"]
    assert rec.year == 2005
    assert rec.container == "PLoS Med"
    assert rec.url == "https://pubmed.ncbi.nlm.nih.gov/16060722/"


def test_ecitmatch_miss_is_an_answer_and_skips_esummary(indexes, fake_http):
    fake_http.add(ECITMATCH, "PLoS Med|2005|2|e999|Ioannidis JP|ref1|NOT_FOUND\n")

    resp = indexes.pubmed_ecitmatch(
        journal="PLoS Med", year=2005, volume="2", first_page="e999",
        author="Ioannidis JP", key="ref1",
    )

    assert resp.responded is True and resp.records == []
    assert not fake_http.calls_to(ESUMMARY)


def test_esearch_then_esummary(indexes, fake_http):
    _pubmed_routes(fake_http)

    resp = indexes.pubmed_esearch("Why most published research findings are false[Title]")

    assert fake_http.calls_to(ESEARCH)[0].params["retmode"] == "json"
    assert [r.pmid for r in resp.records] == ["16060722"]


def test_esearch_sorts_by_relevance(indexes, fake_http):
    """The default is newest-first. Live, the title above returns five recent
    papers that echo it and not the 2005 original — an existence check that
    can miss the most-cited paper of its kind."""
    _pubmed_routes(fake_http)

    indexes.pubmed_esearch("Why most published research findings are false[Title]")

    assert fake_http.calls_to(ESEARCH)[0].params["sort"] == "relevance"


def test_esearch_with_no_ids_skips_esummary(indexes, fake_http):
    fake_http.add(ESEARCH, {"esearchresult": {"count": "0", "idlist": []}})

    resp = indexes.pubmed_esearch("nothing")

    assert resp.responded is True and resp.records == []
    assert not fake_http.calls_to(ESUMMARY)


def test_pubmed_api_key_is_sent_when_configured(indexes, fake_http, creds):
    creds.set(PUBMED_API_KEY="pm-key")
    _pubmed_routes(fake_http)

    indexes.pubmed_esearch("x")

    assert all(c.params.get("api_key") == "pm-key" for c in fake_http.calls)


def test_esummary_reads_retraction_pubtype(indexes, fake_http):
    body = load_fixture("pubmed_esummary.json")
    body["result"]["16060722"]["pubtype"] = ["Journal Article", "Retracted Publication"]
    fake_http.add(ESUMMARY, body)

    (rec,) = indexes.pubmed_summary(["16060722"]).records

    assert rec.is_retracted is True


def test_pubmed_outage_is_not_an_answer(indexes, fake_http):
    fake_http.add(ESEARCH, "", status=500)

    assert indexes.pubmed_esearch("x").responded is False


# ---------------------------------------------------------------------------
# DataCite
# ---------------------------------------------------------------------------

def test_datacite_parses_dataset_records(indexes, fake_http):
    fake_http.add(DATACITE, fixture="datacite_dois.json")

    resp = indexes.datacite("global temperature anomaly")

    call = fake_http.calls[0]
    assert call.params["query"] == "global temperature anomaly"
    assert call.params["page[size]"] == index_clients.REFCHECK_MAX_CANDIDATES
    first = resp.records[0]
    assert first.title == "Climate Variability and West Antarctic Ice Sheet Collapse"
    assert first.authors[0] == "Blasco Navarro"
    assert first.year == 2026
    assert first.doi == "10.5281/zenodo.20426843"
    assert first.container == "Zenodo"
    assert first.work_type == "Dataset"
    assert first.url == "https://zenodo.org/doi/10.5281/zenodo.20426843"


def test_datacite_not_found_is_an_answer(indexes, fake_http):
    fake_http.add(DATACITE, {"errors": []}, status=404)

    resp = indexes.datacite("x")

    assert resp.responded is True and resp.records == []


def test_datacite_outage_is_not_an_answer(indexes, fake_http):
    fake_http.add(DATACITE, "", status=503)

    assert indexes.datacite("x").responded is False
