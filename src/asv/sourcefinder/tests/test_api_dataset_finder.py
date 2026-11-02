"""Request building and response parsing for the dataset registries that
``DatasetFinder`` searches: Zenodo, Figshare, DataCite, HuggingFace, Kaggle.

These replaced browser scrapes that returned zero links every time, so the
regression to guard against is the quiet one — a registry that answers 200
and contributes nothing because a field moved. Each registry's payload is a
real captured response.
"""

import sys
import types

import pytest
import requests

from asv.sourcefinder import dataset_finder as df_module
from asv.sourcefinder.config import (
    DATACITE_SEARCH_API,
    DEFAULT_TOP_K,
    FIGSHARE_SEARCH_API,
    HUGGINGFACE_DATASETS_API,
    ZENODO_API,
)
from asv.sourcefinder.dataset_finder import DatasetFinder

from .api_fakes import load_fixture

pytestmark = pytest.mark.unit

QUERY = "global surface temperature anomaly"


class StubLLM:
    def __init__(self, query=QUERY):
        self.query = query

    def call_llm(self, prompt, **kwargs):
        if kwargs.get("task_name") == "dataset_query_building":
            return {"query": self.query, "measures": []}
        return {}


@pytest.fixture
def finder(fake_http):
    f = DatasetFinder(llm_client=StubLLM())
    f.session = fake_http
    return f


def _registries(fake_http):
    fake_http.add(ZENODO_API, fixture="zenodo_records.json")
    fake_http.add(FIGSHARE_SEARCH_API, fixture="figshare_search.json", method="POST")
    fake_http.add(DATACITE_SEARCH_API, fixture="datacite_dois.json")
    fake_http.add(HUGGINGFACE_DATASETS_API, fixture="huggingface_datasets.json")


# ---------------------------------------------------------------------------
# Zenodo
# ---------------------------------------------------------------------------

def test_zenodo_request(finder, fake_http):
    fake_http.add(ZENODO_API, fixture="zenodo_records.json")

    finder._search_zenodo(QUERY)

    assert fake_http.calls[0].params == {"q": QUERY, "size": DEFAULT_TOP_K, "type": "dataset"}


def test_zenodo_returns_a_direct_file_link(finder, fake_http):
    """The record page is HTML the downloader would refuse; the file's
    ``links.self`` is the bytes."""
    fake_http.add(ZENODO_API, fixture="zenodo_records.json")

    (hit,) = finder._search_zenodo(QUERY)

    assert hit["url"].startswith("https://zenodo.org/api/records/6461153/files/")
    assert hit["url"].endswith(".xls/content")
    assert hit["source"] == "zenodo"
    assert hit["title"].startswith("Global Surface Temperature Changes")
    assert hit["query"] == QUERY


def test_zenodo_skips_records_with_no_tabular_file(finder, fake_http):
    """The fixture's second record is real and holds only NetCDF (``.nc``)
    files — nothing the downloader can parse — so it must not be offered."""
    fake_http.add(ZENODO_API, fixture="zenodo_records.json")

    hits = finder._search_zenodo(QUERY)

    assert not any(".nc" in h["url"] for h in hits)
    assert len(hits) == 1


def test_zenodo_error_is_empty(finder, fake_http):
    fake_http.add(ZENODO_API, "", status=403)

    assert finder._search_zenodo(QUERY) == []


# ---------------------------------------------------------------------------
# Figshare
# ---------------------------------------------------------------------------

def test_figshare_searches_by_post_with_a_json_body(finder, fake_http):
    """GET on this endpoint 404s with a routing error that reads like "no
    results"; it has to be a POST."""
    fake_http.add(FIGSHARE_SEARCH_API, fixture="figshare_search.json", method="POST")

    finder._search_figshare(QUERY)

    (call,) = fake_http.calls
    assert call.method == "POST"
    assert call.json == {"search_for": QUERY, "limit": DEFAULT_TOP_K, "item_type": 3}


def test_figshare_parses_articles(finder, fake_http):
    fake_http.add(FIGSHARE_SEARCH_API, fixture="figshare_search.json", method="POST")

    hits = finder._search_figshare(QUERY)

    assert hits[0]["url"] == "https://api.figshare.com/v2/articles/34076892"
    assert hits[0]["title"].startswith("Managing Mango for a Changing Climate")
    assert all(h["source"] == "figshare" for h in hits)


def test_figshare_error_is_empty(finder, fake_http):
    fake_http.add(FIGSHARE_SEARCH_API, {"message": "bad"}, status=400, method="POST")

    assert finder._search_figshare(QUERY) == []


# ---------------------------------------------------------------------------
# DataCite
# ---------------------------------------------------------------------------

def test_datacite_asks_for_datasets_only(finder, fake_http):
    fake_http.add(DATACITE_SEARCH_API, fixture="datacite_dois.json")

    finder._search_datacite(QUERY)

    assert fake_http.calls[0].params == {
        "query": QUERY, "page[size]": DEFAULT_TOP_K, "resource-type-id": "dataset",
    }


def test_datacite_parses_records(finder, fake_http):
    fake_http.add(DATACITE_SEARCH_API, fixture="datacite_dois.json")

    hits = finder._search_datacite(QUERY)

    assert hits[0]["url"] == "https://zenodo.org/doi/10.5281/zenodo.20426843"
    assert hits[0]["title"] == "Climate Variability and West Antarctic Ice Sheet Collapse"
    assert hits[0]["description"] == "Zenodo"


def test_datacite_falls_back_to_the_doi_url(finder, fake_http):
    body = load_fixture("datacite_dois.json")
    del body["data"][0]["attributes"]["url"]
    fake_http.add(DATACITE_SEARCH_API, body)

    hits = finder._search_datacite(QUERY)

    assert hits[0]["url"] == "https://doi.org/10.5281/zenodo.20426843"


# ---------------------------------------------------------------------------
# HuggingFace
# ---------------------------------------------------------------------------

def test_huggingface_request_and_parse(finder, fake_http):
    fake_http.add(HUGGINGFACE_DATASETS_API, fixture="huggingface_datasets.json")

    hits = finder._search_huggingface(QUERY)

    assert fake_http.calls[0].params == {"search": QUERY, "limit": DEFAULT_TOP_K}
    assert [h["title"] for h in hits] == [
        "WasuratS/ECMWF_Thailand_Land_Air_Temperatures", "tarunchand/temperature",
    ]
    assert hits[1]["url"] == "https://huggingface.co/api/datasets/tarunchand/temperature/parquet"
    assert "format:csv" in hits[1]["description"]


def test_huggingface_skips_rows_without_an_id(finder, fake_http):
    fake_http.add(HUGGINGFACE_DATASETS_API, [{"author": "x"}])

    assert finder._search_huggingface(QUERY) == []


# ---------------------------------------------------------------------------
# Kaggle (SDK, not HTTP)
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_kaggle(monkeypatch):
    """Stand-in for the ``kaggle`` package, which authenticates on import."""
    searched = []

    class KaggleApi:
        def authenticate(self):
            pass

        def dataset_list(self, search):
            searched.append(search)
            return [types.SimpleNamespace(ref="noaa/global-temps", title="Global temps",
                                          subtitle="Monthly anomalies")]

    extended = types.ModuleType("kaggle.api.kaggle_api_extended")
    extended.KaggleApi = KaggleApi
    monkeypatch.setitem(sys.modules, "kaggle", types.ModuleType("kaggle"))
    monkeypatch.setitem(sys.modules, "kaggle.api", types.ModuleType("kaggle.api"))
    monkeypatch.setitem(sys.modules, "kaggle.api.kaggle_api_extended", extended)
    return searched


def test_kaggle_parses_sdk_results(finder, fake_kaggle):
    (hit,) = finder._search_kaggle(QUERY)

    assert fake_kaggle == [QUERY]
    assert hit["url"] == "https://www.kaggle.com/datasets/noaa/global-temps"
    assert hit["source"] == "kaggle"


def test_kaggle_failure_is_empty(finder, monkeypatch):
    monkeypatch.setitem(sys.modules, "kaggle", None)  # import raises

    assert finder._search_kaggle(QUERY) == []


# ---------------------------------------------------------------------------
# _search_repositories — the pooled search
# ---------------------------------------------------------------------------

def test_every_registry_is_asked_with_the_llm_query(finder, fake_http):
    _registries(fake_http)

    hits = finder._search_repositories("The global mean temperature rose 1.1C since 1900 [4].")

    assert {h["source"] for h in hits} == {"zenodo", "figshare", "datacite", "huggingface"}
    assert all(h["query"] == QUERY for h in hits)


def test_one_registry_failing_does_not_stop_the_others(finder, fake_http):
    fake_http.add(ZENODO_API, raises=requests.ConnectionError("down"))
    fake_http.add(FIGSHARE_SEARCH_API, fixture="figshare_search.json", method="POST")
    fake_http.add(DATACITE_SEARCH_API, fixture="datacite_dois.json")
    fake_http.add(HUGGINGFACE_DATASETS_API, fixture="huggingface_datasets.json")

    hits = finder._search_repositories("claim")

    assert {h["source"] for h in hits} == {"figshare", "datacite", "huggingface"}


def test_kaggle_is_asked_only_with_credentials(finder, fake_http, fake_kaggle, creds):
    _registries(fake_http)
    finder._search_repositories("claim")
    assert fake_kaggle == []

    creds.set(KAGGLE_USERNAME="u", KAGGLE_KEY="k")
    finder._search_repositories("another claim")
    assert fake_kaggle == [QUERY]


def test_data_gov_is_off_by_default(finder, fake_http):
    _registries(fake_http)
    assert df_module.ENABLE_DATA_GOV is False

    finder._search_repositories("claim")

    assert not fake_http.calls_to("https://catalog.data.gov")


def test_query_falls_back_to_the_claim_when_the_llm_fails(fake_http):
    class Broken:
        def call_llm(self, *a, **k):
            raise RuntimeError("quota")

    f = DatasetFinder(llm_client=Broken())
    f.session = fake_http
    _registries(fake_http)
    claim = "Unemployment fell below 4% in 2019 according to BLS data, a fifty-year low."

    f._search_repositories(claim)

    assert fake_http.calls_to(ZENODO_API)[0].params["q"] == claim[:100]
