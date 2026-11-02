"""Live contract tests: do the real services still answer in the recorded shape?

Every other API test in this package runs against a payload captured once and
committed under ``fixtures/api/``. Those tests prove the parsers handle *that*
shape; they cannot notice the service changing. These tests can: each one
drives the real client against the real endpoint, through the real
``PoliteSession`` with the response cache off, and checks the parsed result.

Opt-in, because they need the network and are slow (the polite per-host clock
alone is ~1s a request)::

    ASV_LIVE_API_TESTS=1 pytest -m live -p no:cacheprovider --no-cov

They use your real ``.env``. Services that need a credential you have not set
are skipped, not failed.

When one fails, the parser and its fixture are out of date together. Re-capture
the payload, trim it to the fields the parser reads, update the offline test,
then fix the parser — in that order, so the offline suite pins the new shape.
``scripts/probe_existence_apis.py`` prints the live shapes of the five index
services.

Reference work throughout: Ioannidis JP (2005), *Why most published research
findings are false*, PLoS Med 2(8): e124 — open access, in PMC, indexed by
every service here.
"""

import os

import pytest

from asv.core import credentials as creds
from asv.sourcefinder import polite_http

pytestmark = [
    pytest.mark.live,
    pytest.mark.slow,
    pytest.mark.skipif(
        os.getenv("ASV_LIVE_API_TESTS", "").strip() not in ("1", "true", "yes"),
        reason="live API tests are opt-in: set ASV_LIVE_API_TESTS=1",
    ),
]

DOI = "10.1371/journal.pmed.0020124"
TITLE = "Why most published research findings are false"
PMCID = "PMC1182327"
PMC_XML = f"https://www.ebi.ac.uk/europepmc/webservices/rest/{PMCID}/fullTextXML"


@pytest.fixture(autouse=True)
def _uncached(monkeypatch):
    """A cached body would make a live test a replay of last week."""
    monkeypatch.setattr(polite_http, "CACHE_ENABLED", False)
    polite_http.reset_circuit_breakers()


def _need(*names):
    missing = [n for n in names if not creds.get(n)]
    if missing:
        pytest.skip("needs " + ", ".join(missing))


def _need_email():
    if not creds.contact_email():
        pytest.skip("needs UNPAYWALL_EMAIL or ASV_CONTACT_EMAIL")


@pytest.fixture
def indexes():
    from asv.sourcefinder.index_clients import BibliographicIndexes
    return BibliographicIndexes(contact_email=creds.contact_email())


@pytest.fixture
def fulltext():
    from asv.sourcefinder.fulltext_apis import FullTextAPIs
    return FullTextAPIs()


@pytest.fixture
def finder():
    from asv.sourcefinder.academic_paper_finder import AcademicPaperFinder
    return AcademicPaperFinder()


@pytest.fixture
def datasets():
    from asv.sourcefinder.dataset_finder import DatasetFinder
    return DatasetFinder(llm_client=None)


# ---------------------------------------------------------------------------
# Bibliographic indexes
# ---------------------------------------------------------------------------

def test_crossref(indexes):
    resp = indexes.crossref_by_doi(DOI)
    assert resp.responded, resp.error
    (rec,) = resp.records
    assert rec.title.lower().startswith("why most published research findings")
    assert "Ioannidis" in rec.authors
    assert rec.year == 2005
    assert rec.container == "PLoS Medicine"


def test_openalex(indexes):
    _need_email()
    resp = indexes.openalex_by_doi(DOI)
    assert resp.responded, resp.error
    rec = resp.records[0]
    assert rec.doi.lower() == DOI
    assert rec.pmid == "16060722"
    assert "Ioannidis" in rec.authors
    assert rec.is_retracted is False


def test_europepmc(indexes):
    resp = indexes.europepmc(f'DOI:"{DOI}"')
    assert resp.responded, resp.error
    rec = resp.records[0]
    assert rec.pmid == "16060722"
    assert "Ioannidis" in rec.authors
    assert rec.container and "plos" in rec.container.lower()


def test_pubmed_ecitmatch(indexes):
    resp = indexes.pubmed_ecitmatch(
        journal="PLoS Med", year=2005, volume="2", first_page="e124",
        author="Ioannidis JP", key="live",
    )
    assert resp.responded, resp.error
    (rec,) = resp.records
    assert rec.pmid == "16060722"
    assert rec.doi == DOI
    assert rec.authors[0] == "Ioannidis"


def test_pubmed_esearch(indexes):
    resp = indexes.pubmed_esearch(f"{TITLE}[Title]")
    assert resp.responded, resp.error
    assert "16060722" in [r.pmid for r in resp.records]


def test_datacite_index(indexes):
    resp = indexes.datacite("global temperature")
    assert resp.responded, resp.error
    assert resp.records and resp.records[0].title and resp.records[0].doi


# ---------------------------------------------------------------------------
# Full-text locators
# ---------------------------------------------------------------------------

def test_europepmc_fulltext_route(fulltext):
    cands, meta = fulltext.europepmc(doi=DOI)
    assert meta.get("pmcid") == PMCID
    assert PMC_XML in [c.url for c in cands]


def test_pmc_id_converter(fulltext):
    assert fulltext.pmcid_for_doi(DOI) == PMCID


def test_openalex_locations(fulltext):
    _need_email()
    cands, recovered = fulltext.openalex(doi=DOI)
    assert recovered == DOI
    assert any(c.kind == "repository_pdf" for c in cands)


def test_core(fulltext):
    _need("CORE_API_KEY")
    assert fulltext.core(TITLE, doi=DOI)


def test_arxiv(fulltext):
    urls = [c.url for c in fulltext.arxiv("Attention is all you need")]
    assert any("1706.03762" in u for u in urls)


# ---------------------------------------------------------------------------
# AcademicPaperFinder resolvers
# ---------------------------------------------------------------------------

def test_unpaywall(finder):
    _need("UNPAYWALL_EMAIL")
    cands = finder._try_unpaywall(DOI)
    assert any(c.kind in ("repository_pdf", "repository_landing") for c in cands)


def test_semantic_scholar_search(finder):
    # Keyless S2 is a shared pool that 429s often enough to make this flaky.
    _need("SEMANTIC_SCHOLAR_API_KEY")
    cands, recovered = finder._try_semantic_scholar_by_text(TITLE, expected_title=TITLE)
    assert recovered, "S2 returned no title-matching row with a DOI"
    assert cands


def test_crossref_bibliographic_resolution(finder):
    parsed = {"title": TITLE, "first_author": "Ioannidis", "journal": "PLoS Med"}
    assert finder._resolve_doi_via_crossref(parsed, TITLE)


# ---------------------------------------------------------------------------
# Dataset registries
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("registry", ["zenodo", "figshare", "datacite", "huggingface"])
def test_dataset_registry(datasets, registry):
    hits = getattr(datasets, f"_search_{registry}")("temperature")
    assert hits, f"{registry} returned no usable candidates for a broad query"
    assert all(h["url"].startswith("https://") for h in hits)
