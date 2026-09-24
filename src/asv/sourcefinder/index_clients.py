"""Clients for the free bibliographic indexes — Tier 0.6 (docs/TIER0_PLAN.md §6.3).

Five keyless services, normalised onto one ``IndexRecord`` shape so the matcher
in ``reference_verifier.py`` never has to care which index a candidate came
from:

| Index       | Coverage                             | Auth                       |
|-------------|--------------------------------------|----------------------------|
| Crossref    | ~160M DOIs, all disciplines          | none (``mailto`` = polite) |
| OpenAlex    | ~250M works, best recall; retraction | none (``mailto`` = polite) |
| Europe PMC  | biomedical, incl. PubMed + preprints | none                       |
| PubMed      | biomedical; ``ecitmatch`` is exact   | optional key (3 -> 10 rps) |
| DataCite    | datasets, software, theses           | none                       |

Every extractor is written defensively (``.get()`` chains, never index-into-list
without a length check) because these are third-party JSON shapes that change
without notice. ``scripts/probe_existence_apis.py`` prints the live shapes and
is the thing to run when something here starts returning nothing.

Each method returns ``IndexResponse``, which distinguishes *"the index answered
and had no match"* from *"the index did not answer"*. That distinction is the
entire basis of the two-index quorum rule that prevents an API outage from
reading as an accusation of fabrication.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests

from .config import (
    ASV_CONTACT_EMAIL,
    CROSSREF_WORKS_API,
    DATACITE_API,
    EUROPEPMC_API,
    OPENALEX_API,
    PUBMED_API_KEY,
    PUBMED_ECITMATCH_API,
    PUBMED_ESEARCH_API,
    PUBMED_ESUMMARY_API,
    REFCHECK_MAX_CANDIDATES,
    REFCHECK_MIN_INTERVAL_SECONDS,
    REFCHECK_TIMEOUT,
)

logger = logging.getLogger(__name__)


@dataclass
class IndexRecord:
    """One candidate match, normalised across indexes."""
    index: str
    title: Optional[str] = None
    authors: List[str] = field(default_factory=list)   # surnames, lowercased on use
    year: Optional[int] = None
    doi: Optional[str] = None
    pmid: Optional[str] = None
    container: Optional[str] = None                    # journal / venue
    url: Optional[str] = None
    work_type: Optional[str] = None
    is_retracted: Optional[bool] = None
    retraction_notice_url: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class IndexResponse:
    """The result of asking one index.

    ``responded`` is deliberately separate from ``records``: an index that
    answered "no match" is evidence, an index that timed out is not.
    """
    index: str
    responded: bool
    records: List[IndexRecord] = field(default_factory=list)
    error: Optional[str] = None


class _PoliteSession:
    """A ``requests.Session`` with a per-host minimum interval between calls.

    SOURCE_ACQUISITION.md traces the 49% -> 31% acquisition decline on identical
    input to rate-limit accumulation with no backoff and no politeness. Tier 0.6
    adds ~700 requests per run, so it ships with the politeness that layer
    lacks rather than repeating the mistake at greater volume.
    """

    def __init__(self, user_agent: str, min_interval: float = REFCHECK_MIN_INTERVAL_SECONDS):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = user_agent
        self.session.headers["Accept"] = "application/json"
        self._min_interval = min_interval
        self._last_call: Dict[str, float] = {}
        self._lock = threading.Lock()

    def get(self, url: str, **kwargs) -> requests.Response:
        host = urlparse(url).netloc
        with self._lock:
            last = self._last_call.get(host, 0.0)
            wait = self._min_interval - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
            self._last_call[host] = time.monotonic()
        kwargs.setdefault("timeout", REFCHECK_TIMEOUT)
        return self.session.get(url, **kwargs)


def _first(seq: Any) -> Optional[Any]:
    """First element of a list-ish value, or the value itself, or None."""
    if isinstance(seq, (list, tuple)):
        return seq[0] if seq else None
    return seq or None


def _year_from_crossref(node: Dict[str, Any]) -> Optional[int]:
    for key in ("issued", "published-print", "published-online", "created"):
        parts = (node.get(key) or {}).get("date-parts") or []
        first = _first(parts)
        if isinstance(first, (list, tuple)) and first:
            try:
                return int(first[0])
            except (TypeError, ValueError):
                continue
    return None


def _surname(name: Any) -> Optional[str]:
    """Best-effort surname from the many author shapes these APIs return."""
    if isinstance(name, dict):
        for key in ("family", "familyName", "lastName", "last_name"):
            if name.get(key):
                return str(name[key])
        display = name.get("display_name") or name.get("name") or name.get("literal")
        if display:
            return str(display).split()[-1].strip(",")
        return None
    if isinstance(name, str) and name.strip():
        # "Smith AB" (PubMed) or "Smith, A. B." — surname leads in both.
        return name.replace(",", " ").split()[0]
    return None


class BibliographicIndexes:
    """Query the free indexes. One instance per run; sessions are reused."""

    def __init__(self, contact_email: str = ASV_CONTACT_EMAIL):
        self.contact_email = contact_email or ""
        ua = (
            "ASV-pipeline/1.0 (automated source validation; "
            f"{'mailto:' + self.contact_email if self.contact_email else 'contact via project repo'})"
        )
        if not self.contact_email:
            logger.warning(
                "No ASV_CONTACT_EMAIL/UNPAYWALL_EMAIL set — Crossref and OpenAlex "
                "requests will use the shared anonymous pool and may be throttled."
            )
        self._http = _PoliteSession(ua)

    # -- Crossref -----------------------------------------------------------

    def crossref_by_doi(self, doi: str) -> IndexResponse:
        try:
            resp = self._http.get(f"{CROSSREF_WORKS_API}/{doi}", params=self._mailto())
            if resp.status_code == 404:
                return IndexResponse("crossref", responded=True, records=[])
            resp.raise_for_status()
            msg = resp.json().get("message") or {}
        except Exception as e:
            return IndexResponse("crossref", responded=False, error=str(e))
        return IndexResponse("crossref", responded=True, records=[self._crossref_record(msg)])

    def crossref_bibliographic(self, query: str) -> IndexResponse:
        params = self._mailto()
        params.update({
            "query.bibliographic": query[:400],
            "rows": REFCHECK_MAX_CANDIDATES,
            "select": "DOI,title,author,issued,container-title,URL,type,update-to",
        })
        try:
            resp = self._http.get(CROSSREF_WORKS_API, params=params)
            if resp.status_code in (400, 404):
                return IndexResponse("crossref", responded=True, records=[])
            resp.raise_for_status()
            items = (resp.json().get("message") or {}).get("items") or []
        except Exception as e:
            return IndexResponse("crossref", responded=False, error=str(e))
        return IndexResponse(
            "crossref", responded=True,
            records=[self._crossref_record(i) for i in items],
        )

    def _crossref_record(self, node: Dict[str, Any]) -> IndexRecord:
        retracted = None
        notice = None
        for upd in node.get("update-to") or []:
            if str(upd.get("type", "")).lower() in ("retraction", "withdrawal"):
                retracted = True
                notice = upd.get("URL")
        return IndexRecord(
            index="crossref",
            title=_first(node.get("title")),
            authors=[s for s in (_surname(a) for a in node.get("author") or []) if s],
            year=_year_from_crossref(node),
            doi=node.get("DOI"),
            container=_first(node.get("container-title")),
            url=node.get("URL") or (f"https://doi.org/{node['DOI']}" if node.get("DOI") else None),
            work_type=node.get("type"),
            is_retracted=retracted,
            retraction_notice_url=notice,
            raw=node,
        )

    # -- OpenAlex -----------------------------------------------------------

    def openalex_by_doi(self, doi: str) -> IndexResponse:
        params = self._mailto()
        params.update({"filter": f"doi:{doi}", "per-page": 1})
        return self._openalex(params)

    def openalex_by_title(self, title: str) -> IndexResponse:
        params = self._mailto()
        params.update({
            "filter": f"title.search:{title[:250]}",
            "per-page": REFCHECK_MAX_CANDIDATES,
        })
        resp = self._openalex(params)
        if resp.responded and resp.records:
            return resp
        # `title.search` is strict; fall back to full-text search for recall.
        params = self._mailto()
        params.update({"search": title[:250], "per-page": REFCHECK_MAX_CANDIDATES})
        return self._openalex(params)

    def _openalex(self, params: Dict[str, Any]) -> IndexResponse:
        try:
            resp = self._http.get(OPENALEX_API, params=params)
            if resp.status_code in (400, 404):
                return IndexResponse("openalex", responded=True, records=[])
            resp.raise_for_status()
            results = resp.json().get("results") or []
        except Exception as e:
            return IndexResponse("openalex", responded=False, error=str(e))
        return IndexResponse(
            "openalex", responded=True,
            records=[self._openalex_record(r) for r in results],
        )

    @staticmethod
    def _openalex_record(node: Dict[str, Any]) -> IndexRecord:
        doi = node.get("doi") or ""
        doi = doi.replace("https://doi.org/", "") or None
        source = ((node.get("primary_location") or {}).get("source") or {})
        return IndexRecord(
            index="openalex",
            title=node.get("title") or node.get("display_name"),
            authors=[
                s for s in (
                    _surname((a or {}).get("author"))
                    for a in node.get("authorships") or []
                ) if s
            ],
            year=node.get("publication_year"),
            doi=doi,
            pmid=(str((node.get("ids") or {}).get("pmid") or "").rsplit("/", 1)[-1] or None),
            container=source.get("display_name"),
            url=(node.get("doi") or (node.get("primary_location") or {}).get("landing_page_url")),
            work_type=node.get("type"),
            is_retracted=node.get("is_retracted"),
            raw=node,
        )

    # -- Europe PMC ---------------------------------------------------------

    def europepmc(self, query: str) -> IndexResponse:
        params = {
            "query": query[:400],
            "format": "json",
            "pageSize": REFCHECK_MAX_CANDIDATES,
            "resultType": "core",
        }
        try:
            resp = self._http.get(EUROPEPMC_API, params=params)
            if resp.status_code in (400, 404):
                return IndexResponse("europepmc", responded=True, records=[])
            resp.raise_for_status()
            results = ((resp.json().get("resultList") or {}).get("result")) or []
        except Exception as e:
            return IndexResponse("europepmc", responded=False, error=str(e))
        return IndexResponse(
            "europepmc", responded=True,
            records=[self._europepmc_record(r) for r in results],
        )

    @staticmethod
    def _europepmc_record(node: Dict[str, Any]) -> IndexRecord:
        pub_types = [
            str(t).lower()
            for t in ((node.get("pubTypeList") or {}).get("pubType") or [])
        ]
        retracted = any("retract" in t for t in pub_types) or None
        concern = any("expression of concern" in t for t in pub_types)
        authors = [
            s for s in (
                _surname(a) for a in
                ((node.get("authorList") or {}).get("author") or [])
            ) if s
        ]
        if not authors and node.get("authorString"):
            authors = [
                _surname(part) or ""
                for part in str(node["authorString"]).split(",")
            ]
            authors = [a for a in authors if a]
        year = None
        try:
            year = int(node.get("pubYear")) if node.get("pubYear") else None
        except (TypeError, ValueError):
            year = None
        return IndexRecord(
            index="europepmc",
            title=node.get("title"),
            authors=authors,
            year=year,
            doi=node.get("doi"),
            pmid=node.get("pmid"),
            container=node.get("journalTitle"),
            url=(f"https://doi.org/{node['doi']}" if node.get("doi") else node.get("fullTextUrl")),
            work_type=_first(pub_types),
            is_retracted=retracted,
            retraction_notice_url=None,
            raw={**node, "_concern_raised": concern},
        )

    # -- PubMed -------------------------------------------------------------

    def pubmed_ecitmatch(
        self, *, journal: str, year: Any, volume: str, first_page: str, author: str, key: str
    ) -> IndexResponse:
        """Exact citation match. Purpose-built for this question, so when the
        parsed reference has journal + year + volume + first page, it beats any
        fuzzy title comparison."""
        bdata = f"{journal}|{year}|{volume}|{first_page}|{author}|{key}|"
        params = {"db": "pubmed", "retmode": "xml", "bdata": bdata}
        if PUBMED_API_KEY:
            params["api_key"] = PUBMED_API_KEY
        try:
            resp = self._http.get(PUBMED_ECITMATCH_API, params=params)
            resp.raise_for_status()
            body = resp.text.strip()
        except Exception as e:
            return IndexResponse("pubmed", responded=False, error=str(e))

        pmid: Optional[str] = None
        for line in body.splitlines():
            tail = line.rsplit("|", 1)[-1].strip()
            if tail.isdigit():
                pmid = tail
                break
        if not pmid:
            return IndexResponse("pubmed", responded=True, records=[])
        return self.pubmed_summary([pmid])

    def pubmed_esearch(self, term: str) -> IndexResponse:
        params = {
            "db": "pubmed", "term": term[:400], "retmode": "json",
            "retmax": REFCHECK_MAX_CANDIDATES,
        }
        if PUBMED_API_KEY:
            params["api_key"] = PUBMED_API_KEY
        try:
            resp = self._http.get(PUBMED_ESEARCH_API, params=params)
            resp.raise_for_status()
            ids = ((resp.json().get("esearchresult") or {}).get("idlist")) or []
        except Exception as e:
            return IndexResponse("pubmed", responded=False, error=str(e))
        if not ids:
            return IndexResponse("pubmed", responded=True, records=[])
        return self.pubmed_summary(ids)

    def pubmed_summary(self, pmids: List[str]) -> IndexResponse:
        params = {"db": "pubmed", "id": ",".join(pmids), "retmode": "json"}
        if PUBMED_API_KEY:
            params["api_key"] = PUBMED_API_KEY
        try:
            resp = self._http.get(PUBMED_ESUMMARY_API, params=params)
            resp.raise_for_status()
            result = resp.json().get("result") or {}
        except Exception as e:
            return IndexResponse("pubmed", responded=False, error=str(e))

        records = []
        for uid in result.get("uids", []):
            node = result.get(uid) or {}
            pub_types = [str(t).lower() for t in node.get("pubtype") or []]
            doi = None
            for aid in node.get("articleids") or []:
                if str(aid.get("idtype", "")).lower() == "doi":
                    doi = aid.get("value")
                    break
            year = None
            pubdate = str(node.get("pubdate") or "")
            if pubdate[:4].isdigit():
                year = int(pubdate[:4])
            records.append(IndexRecord(
                index="pubmed",
                title=node.get("title"),
                authors=[s for s in (_surname(a) for a in node.get("authors") or []) if s],
                year=year,
                doi=doi,
                pmid=uid,
                container=node.get("source") or node.get("fulljournalname"),
                url=f"https://pubmed.ncbi.nlm.nih.gov/{uid}/",
                work_type=_first(pub_types),
                is_retracted=(any("retracted publication" in t for t in pub_types) or None),
                raw={**node, "_concern_raised": any("expression of concern" in t for t in pub_types)},
            ))
        return IndexResponse("pubmed", responded=True, records=records)

    # -- DataCite -----------------------------------------------------------

    def datacite(self, query: str) -> IndexResponse:
        params = {"query": query[:300], "page[size]": REFCHECK_MAX_CANDIDATES}
        try:
            resp = self._http.get(DATACITE_API, params=params)
            if resp.status_code in (400, 404):
                return IndexResponse("datacite", responded=True, records=[])
            resp.raise_for_status()
            data = resp.json().get("data") or []
        except Exception as e:
            return IndexResponse("datacite", responded=False, error=str(e))

        records = []
        for node in data:
            attrs = node.get("attributes") or {}
            title = _first(attrs.get("titles"))
            records.append(IndexRecord(
                index="datacite",
                title=(title or {}).get("title") if isinstance(title, dict) else title,
                authors=[s for s in (_surname(c) for c in attrs.get("creators") or []) if s],
                year=attrs.get("publicationYear"),
                doi=attrs.get("doi"),
                container=attrs.get("publisher"),
                url=attrs.get("url") or (f"https://doi.org/{attrs['doi']}" if attrs.get("doi") else None),
                work_type=((attrs.get("types") or {}).get("resourceTypeGeneral")),
                raw=node,
            ))
        return IndexResponse("datacite", responded=True, records=records)

    # -- helpers ------------------------------------------------------------

    def _mailto(self) -> Dict[str, Any]:
        return {"mailto": self.contact_email} if self.contact_email else {}
