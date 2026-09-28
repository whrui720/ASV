"""Full-text locators — SOURCE_ACQUISITION.md §6, Tiers 1 and 2.

``index_clients.py`` answers *"does this reference exist?"*. This module answers
the different and harder question *"where can I read it?"*, and it is where the
acquisition rate is actually won: 80% of our failed fetches are publisher 403s,
and the fix is almost never to try that publisher harder — it is to find the
repository mirror that the same paper is sitting in.

Every locator returns ``SourceCandidate`` objects carrying a **kind**, and the
kind is the ranking. A JATS full-text XML endpoint beats a repository PDF beats
a publisher landing page, regardless of which service surfaced it, because that
ordering tracks the probability that the bytes contain the sentence we need to
quote.

Endpoint shapes here were verified live rather than recalled, and two of them
are easy to get wrong:

* Europe PMC full text is ``/webservices/rest/{PMCID}/fullTextXML`` — with the
  PMCID alone in the path. The ``/{source}/{id}/`` form documented for other
  operations 404s here for every record tested.
* Figshare's article search is **POST** with a JSON body. The GET form returns
  404 with a routing error, which reads like "no results" if you are not looking.

Tier 2 (Wiley / Elsevier / Springer) needs free registration. Those locators
return nothing at all when their key is absent, rather than emitting a URL that
is guaranteed to 400 — the Wiley endpoint's own error message,
``No TDM Client Token was found in the request``, is what put it on this list.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, urlparse, urlunparse

from asv.core import credentials as creds

from .polite_http import PoliteSession

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Candidate model and ranking
# ---------------------------------------------------------------------------

#: Lower is better. This ordering *is* the F1 fix: the old cascade stopped at
#: the first API that returned anything, so a single publisher landing page
#: from Unpaywall shadowed the PMC mirror that would have worked.
KIND_RANK: Dict[str, int] = {
    "fulltext_xml": 0,        # JATS/XML — machine-readable, no PDF parsing loss
    "repository_pdf": 1,      # PMC, arXiv, institutional repo, CORE
    "repository_landing": 2,
    "publisher_pdf": 3,
    "publisher_landing": 4,
    "search_guess": 5,        # Google Scholar and friends
}

#: Hosts that serve author/repository copies rather than the publisher's own
#: paywalled rendering. Used when an API does not tell us the host type.
_REPOSITORY_HOSTS = (
    "ebi.ac.uk", "europepmc.org", "ncbi.nlm.nih.gov", "pmc.ncbi.nlm.nih.gov",
    "arxiv.org", "biorxiv.org", "medrxiv.org", "core.ac.uk", "zenodo.org",
    "osf.io", "figshare.com", "hal.science", "repec.org", "ssrn.com",
    "semanticscholar.org", "citeseerx.ist.psu.edu", "dtic.mil",
)


@dataclass(frozen=True)
class SourceCandidate:
    """One place the cited paper might be readable."""

    url: str
    source: str   # which locator produced it, for the manifest
    kind: str     # ranking class, see KIND_RANK

    @property
    def rank(self) -> int:
        return KIND_RANK.get(self.kind, len(KIND_RANK))


def _is_repository(url: str) -> bool:
    host = (urlparse(url).netloc or "").lower()
    return any(host == h or host.endswith("." + h) or host.endswith(h)
               for h in _REPOSITORY_HOSTS)


def classify(url: str, *, is_pdf: bool, host_type: Optional[str] = None) -> str:
    """Pick a ranking kind from what we know about a URL."""
    repo = host_type == "repository" if host_type else _is_repository(url)
    if repo:
        return "repository_pdf" if is_pdf else "repository_landing"
    return "publisher_pdf" if is_pdf else "publisher_landing"


def _looks_like_pdf(url: str) -> bool:
    low = url.lower()
    return low.endswith(".pdf") or ".pdf?" in low or "pdf=render" in low or "/pdf/" in low


def normalise_url(url: str) -> str:
    """Canonical form for dedupe: lowercase host, no fragment, no trailing slash."""
    try:
        p = urlparse(url.strip())
        path = p.path.rstrip("/") or "/"
        return urlunparse((p.scheme.lower(), p.netloc.lower(), path, "", p.query, ""))
    except Exception:
        return url.strip()


#: ``europepmc.org`` (the website) sits behind a Cloudflare challenge that
#: returns 403 to every scripted request. Its REST mirror on ``www.ebi.ac.uk``
#: does not, and serves the same article as JATS. Any resolver that hands us a
#: europepmc.org article URL is therefore pointing at the right article through
#: the wrong door.
_EPMC_ARTICLE_RE = re.compile(
    r"^https?://(?:www\.)?europepmc\.org/(?:articles?|abstract)/(?:MED/)?(PMC\d+)",
    re.IGNORECASE,
)


def _reroute_known_blocked(c: SourceCandidate) -> Optional[SourceCandidate]:
    """Swap a guaranteed-403 URL for an equivalent that works, or drop it."""
    m = _EPMC_ARTICLE_RE.match(c.url)
    if m:
        return SourceCandidate(
            url=EUROPEPMC_FULLTEXT.format(pmcid=m.group(1).upper()),
            source="europepmc_fulltext", kind="fulltext_xml",
        )
    if "europepmc.org/" in c.url.lower():
        return None  # the site, but not an article we can reroute
    return c


def rank_and_dedupe(
    candidates: List[SourceCandidate], limit: Optional[int] = None
) -> List[SourceCandidate]:
    """Union-then-rank (F1). Keeps the best-ranked entry per distinct URL."""
    best: Dict[str, Tuple[int, int, SourceCandidate]] = {}
    for order, raw in enumerate(candidates):
        if not raw.url or not raw.url.lower().startswith("http"):
            continue
        c = _reroute_known_blocked(raw)
        if c is None:
            continue
        key = normalise_url(c.url)
        incumbent = best.get(key)
        if incumbent is None or c.rank < incumbent[0]:
            best[key] = (c.rank, order, c)
    ordered = [t[2] for t in sorted(best.values(), key=lambda t: (t[0], t[1]))]
    return ordered[:limit] if limit else ordered


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

EUROPEPMC_SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
EUROPEPMC_FULLTEXT = "https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
PMC_IDCONV = "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/"
NCBI_EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
OPENALEX_WORKS = "https://api.openalex.org/works"
CORE_SEARCH = "https://api.core.ac.uk/v3/search/works"
ARXIV_QUERY = "http://export.arxiv.org/api/query"
WILEY_TDM = "https://api.wiley.com/onlinelibrary/tdm/v1/articles/{doi}"
ELSEVIER_ARTICLE = "https://api.elsevier.com/content/article/doi/{doi}"
SPRINGER_OA_JATS = "https://api.springernature.com/openaccess/jats"

_DOI_IN_TEXT = re.compile(r"\b(10\.\d{4,}/\S+?)(?:[,\s\])}]|$)", re.IGNORECASE)


def extract_doi(text: str) -> Optional[str]:
    if not text:
        return None
    m = _DOI_IN_TEXT.search(text)
    return m.group(1).rstrip(".") if m else None


def clean_doi(doi: Optional[str]) -> Optional[str]:
    if not doi:
        return None
    d = str(doi).strip().rstrip(".")
    d = re.sub(r"^https?://(dx\.)?doi\.org/", "", d, flags=re.IGNORECASE)
    return d or None


_WORD_RE = re.compile(r"[a-z0-9]+")


def title_matches(wanted: Optional[str], got: Optional[str], threshold: float = 0.6) -> bool:
    """Is ``got`` plausibly the same work as ``wanted``?

    Every title search here is a *search*: it returns its best row whether or not
    that row is the paper. Accepting it unchecked is how a reference to a 1982
    Cell paper acquires the DOI of an unrelated 2019 review — and from there the
    wrong DOI propagates into Unpaywall, Crossref and the TDM endpoints, and ASV
    judges a claim against the wrong paper while reporting a resolvable source
    URL. That is a false accusation with a citation attached, which
    VALUE_PROPOSITION.md §10 rates the critical risk.

    Token overlap rather than edit distance, because PDF-extracted titles lose
    subtitles and gain fragments of the journal name.
    """
    if not wanted or not got:
        return False
    a = set(_WORD_RE.findall(str(wanted).lower()))
    b = set(_WORD_RE.findall(str(got).lower()))
    if not a or not b:
        return False
    jaccard = len(a & b) / len(a | b)
    containment = len(a & b) / min(len(a), len(b))
    return jaccard >= threshold or containment >= 0.8


class FullTextAPIs:
    """Every full-text locator, over one shared polite session."""

    #: Warn once per process, not once per citation.
    _warned_no_email = False

    def __init__(self, session: Optional[PoliteSession] = None):
        email = creds.contact_email()
        ua = (
            "ASV-pipeline/1.0 (automated source validation; "
            + ("mailto:" + email if email else "contact via project repo")
            + ")"
        )
        self.http = session or PoliteSession(ua, default_headers={"Accept": "application/json"})
        self.email = email

    # -- Europe PMC ---------------------------------------------------------

    def europepmc_search(self, query: str, page_size: int = 3) -> List[Dict[str, Any]]:
        """Raw Europe PMC ``core`` records for a query string."""
        try:
            resp = self.http.get(
                EUROPEPMC_SEARCH,
                params={
                    "query": query[:400], "format": "json",
                    "resultType": "core", "pageSize": page_size,
                },
            )
            if resp.status_code >= 400:
                return []
            return ((resp.json().get("resultList") or {}).get("result")) or []
        except Exception as e:
            logger.debug("  Europe PMC search failed: %s", e)
            return []

    def europepmc(
        self, *, doi: Optional[str] = None, title: Optional[str] = None,
        first_author: Optional[str] = None, year: Optional[Any] = None,
    ) -> Tuple[List[SourceCandidate], Dict[str, Any]]:
        """Locate a paper in Europe PMC and return its full-text routes.

        The single highest-yield addition for a biomedical corpus: Europe PMC
        serves JATS XML for its open-access subset, so we skip PDF extraction
        entirely, and its REST host is not behind the Cloudflare challenge that
        makes ``europepmc.org`` itself unfetchable from a script.
        """
        records: List[Dict[str, Any]] = []
        if doi:
            # A DOI lookup is exact, so its row needs no title check.
            records = self.europepmc_search('DOI:"%s"' % doi, page_size=1)
        if not records and title:
            query = 'TITLE:"%s"' % title.replace('"', "")[:200]
            if first_author:
                query += ' AND AUTH:"%s"' % str(first_author).replace('"', "")
            if year:
                query += " AND PUB_YEAR:%s" % year
            # A title search always returns its best row, match or not. Keep only
            # rows that are plausibly the same work — everything downstream keys
            # off the DOI this step recovers.
            records = [
                r for r in self.europepmc_search(query, page_size=3)
                if title_matches(title, r.get("title"))
            ]
            if not records:
                logger.debug("  Europe PMC title search returned no matching row")

        candidates: List[SourceCandidate] = []
        meta: Dict[str, Any] = {}
        for rec in records[:2]:
            meta.setdefault("doi", rec.get("doi"))
            meta.setdefault("pmid", rec.get("pmid"))
            meta.setdefault("title", rec.get("title"))
            pmcid = rec.get("pmcid")
            if pmcid:
                meta.setdefault("pmcid", pmcid)
                # ``inEPMC`` is Europe PMC telling us whether it actually holds
                # the full text. Asking for ``fullTextXML`` when it does not
                # returns **500**, not 404, so an ungated request both wastes a
                # candidate slot and looks like a server fault.
                candidates.extend(self.pmc_fulltext(
                    pmcid, in_epmc=str(rec.get("inEPMC") or "").upper() == "Y",
                ))
            for entry in ((rec.get("fullTextUrlList") or {}).get("fullTextUrl") or []):
                url = entry.get("url")
                if not url or entry.get("availabilityCode") not in ("OA", "F"):
                    continue
                # europepmc.org itself sits behind a Cloudflare interstitial; its
                # REST mirror (already added above via pmc_fulltext) does not.
                if "europepmc.org" in url:
                    continue
                candidates.append(SourceCandidate(
                    url=url, source="europepmc",
                    kind=classify(url, is_pdf=entry.get("documentStyle") == "pdf"),
                ))
        return candidates, meta

    def pmc_fulltext(self, pmcid: str, *, in_epmc: Optional[bool] = None) -> List[SourceCandidate]:
        """The two machine-readable routes into a PMC deposit.

        Both return JATS; they are listed together because their coverage is not
        identical — Europe PMC mirrors the open-access subset, while NCBI's
        ``efetch`` also answers for deposits Europe PMC has not ingested. For
        older scanned deposits ``efetch`` returns front matter only, which the
        content gate correctly grades ``abstract_only``; best-of-N then keeps
        looking rather than judging against it.

        ``in_epmc=False`` suppresses the Europe PMC route because that endpoint
        answers **500** for an article it does not hold. ``None`` means we only
        know the PMCID (from the ID converter or OpenAlex) and not whether
        Europe PMC has it, so the route is offered speculatively.
        """
        pmcid = str(pmcid).strip()
        if not pmcid:
            return []
        if not pmcid.upper().startswith("PMC"):
            pmcid = "PMC" + pmcid
        numeric = pmcid[3:]
        efetch = (
            NCBI_EFETCH + "?db=pmc&id=" + quote(numeric) + "&retmode=xml"
            + ("&api_key=" + quote(creds.get("PUBMED_API_KEY")) if creds.get("PUBMED_API_KEY") else "")
        )
        out: List[SourceCandidate] = []
        if in_epmc is not False:
            out.append(SourceCandidate(
                url=EUROPEPMC_FULLTEXT.format(pmcid=pmcid),
                source="europepmc_fulltext", kind="fulltext_xml",
            ))
        out.append(SourceCandidate(url=efetch, source="pmc_efetch", kind="fulltext_xml"))
        return out

    def pmcid_for_doi(self, doi: str) -> Optional[str]:
        """DOI -> PMCID via the NCBI ID converter.

        Aimed squarely at the ``asm.org`` / ``aacrjournals.org`` 403s: those
        publishers block us, but most of their articles have a PMC deposit that
        Unpaywall does not always surface.
        """
        params: Dict[str, str] = {"ids": doi, "format": "json", "tool": "asv"}
        if self.email:
            params["email"] = self.email
        try:
            resp = self.http.get(PMC_IDCONV, params=params)
            if resp.status_code >= 400:
                return None
            for rec in resp.json().get("records") or []:
                if rec.get("pmcid"):
                    return str(rec["pmcid"])
        except Exception as e:
            logger.debug("  PMC ID converter failed: %s", e)
        return None

    # -- OpenAlex -----------------------------------------------------------

    def openalex(
        self, *, doi: Optional[str] = None, title: Optional[str] = None
    ) -> Tuple[List[SourceCandidate], Optional[str]]:
        """Every known location of a work, plus a recovered DOI.

        OpenAlex exposes *all* ``locations``, not just the best one — which is
        exactly what union-then-rank needs. Unpaywall returns one opinion;
        OpenAlex returns the list.
        """
        if not self.email:
            # Not a politeness nicety — a hard capability gate. OpenAlex throttles
            # the anonymous pool by *delaying* the response, and it answered 200
            # after 90 seconds for a single DOI lookup here. A read timeout does
            # not catch that (bytes are still arriving), so the only options are
            # to stall the run or to skip. With a contact address the same call
            # returns in well under a second.
            if not FullTextAPIs._warned_no_email:
                FullTextAPIs._warned_no_email = True
                logger.warning(
                    "  No contact email set — skipping OpenAlex. Its anonymous "
                    "pool delays responses ~90s per request; set UNPAYWALL_EMAIL "
                    "or ASV_CONTACT_EMAIL on the config page to enable it."
                )
            return [], None

        params: Dict[str, Any] = {"per-page": 3, "mailto": self.email}
        if doi:
            params["filter"] = "doi:" + doi
        elif title:
            params["filter"] = "title.search:" + title[:250]
        else:
            return [], None

        try:
            resp = self.http.get(OPENALEX_WORKS, params=params)
            if resp.status_code >= 400:
                return [], None
            results = resp.json().get("results") or []
        except Exception as e:
            logger.debug("  OpenAlex failed: %s", e)
            return [], None
        if not results:
            return [], None

        work = results[0]
        # Same reasoning as Europe PMC: `title.search` ranks, it does not verify.
        if title and not doi:
            work = next(
                (w for w in results
                 if title_matches(title, w.get("title") or w.get("display_name"))),
                None,
            )
            if work is None:
                logger.debug("  OpenAlex title search returned no matching row")
                return [], None
        recovered = clean_doi(work.get("doi"))
        candidates: List[SourceCandidate] = []
        locations = list(work.get("locations") or [])
        best = work.get("best_oa_location")
        if best:
            locations.insert(0, best)
        for loc in locations:
            if not isinstance(loc, dict):
                continue
            host_type = ((loc.get("source") or {}).get("type"))
            host_type = "repository" if host_type == "repository" else None
            pdf_url = loc.get("pdf_url")
            if pdf_url:
                candidates.append(SourceCandidate(
                    url=pdf_url, source="openalex",
                    kind=classify(pdf_url, is_pdf=True, host_type=host_type),
                ))
            landing = loc.get("landing_page_url")
            # A non-OA landing page is a paywall we already know we cannot read;
            # including it only wastes one of the candidate slots.
            if landing and loc.get("is_oa"):
                candidates.append(SourceCandidate(
                    url=landing, source="openalex",
                    kind=classify(landing, is_pdf=_looks_like_pdf(landing), host_type=host_type),
                ))
        # A PMC deposit recorded by OpenAlex is a full-text XML route.
        pmcid = (work.get("ids") or {}).get("pmcid")
        if pmcid:
            candidates.extend(self.pmc_fulltext(str(pmcid).rsplit("/", 1)[-1]))
        return candidates, recovered

    # -- CORE ---------------------------------------------------------------

    def core(self, query: str, *, doi: Optional[str] = None) -> List[SourceCandidate]:
        """CORE aggregates ~300M OA papers *from repositories* — the mirror layer
        that routes around publisher blocks.

        Keyless CORE answers 429 to every request, so this is a no-op without a
        key rather than a per-citation stall. The key is free; the config page
        says so next to the field.
        """
        key = creds.get("CORE_API_KEY")
        if not key:
            logger.debug("  CORE_API_KEY not set; skipping CORE (keyless is 429-only)")
            return []
        if not query and not doi:
            return []

        out: List[SourceCandidate] = []
        # DOI first — an exact match beats a title search — then the title, which
        # is the only route for the many references that carry no DOI at all.
        queries = [q for q in (('doi:"%s"' % doi) if doi else None, query[:250] or None) if q]
        for q in queries:
            try:
                resp = self.http.get(
                    CORE_SEARCH, params={"q": q, "limit": 3},
                    headers={"Authorization": "Bearer " + key},
                )
                if resp.status_code >= 400:
                    logger.debug("  CORE returned HTTP %s", resp.status_code)
                    continue
                results = resp.json().get("results") or []
            except Exception as e:
                logger.debug("  CORE failed: %s", e)
                continue
            for item in results[:3]:
                url = item.get("downloadUrl")
                if url:
                    out.append(SourceCandidate(
                        url=url, source="core",
                        kind="repository_pdf" if _looks_like_pdf(url) else "repository_landing",
                    ))
            if out:
                break
        return out

    # -- arXiv --------------------------------------------------------------

    def arxiv(self, title: str) -> List[SourceCandidate]:
        """Preprint mirrors. Cheap, keyless, and the only route for some refs."""
        if not title or len(title) < 12:
            return []
        try:
            resp = self.http.get(
                ARXIV_QUERY,
                params={"search_query": 'ti:"%s"' % title.replace('"', "")[:180],
                        "max_results": 2},
            )
            if resp.status_code >= 400:
                return []
            body = resp.text
        except Exception as e:
            logger.debug("  arXiv failed: %s", e)
            return []
        ids = re.findall(r"<id>https?://arxiv\.org/abs/([^<]+)</id>", body)
        return [
            SourceCandidate(
                url="https://arxiv.org/pdf/" + aid, source="arxiv", kind="repository_pdf",
            )
            for aid in ids[:2]
        ]

    # -- Tier 2: publisher TDM programmes -----------------------------------

    def publisher_tdm(self, doi: str) -> List[SourceCandidate]:
        """Publisher endpoints that turn a 403 into full text — when keyed.

        Each is silent without its credential rather than emitting a URL that is
        certain to fail; a candidate slot spent on a guaranteed 400 is a slot the
        repository mirror does not get.
        """
        out: List[SourceCandidate] = []
        if creds.get("WILEY_TDM_TOKEN"):
            out.append(SourceCandidate(
                url=WILEY_TDM.format(doi=doi), source="wiley_tdm", kind="publisher_pdf",
            ))
        if creds.get("ELSEVIER_API_KEY"):
            out.append(SourceCandidate(
                url=ELSEVIER_ARTICLE.format(doi=doi) + "?httpAccept=text%2Fxml",
                source="elsevier_tdm", kind="fulltext_xml",
            ))
        springer = creds.get("SPRINGER_API_KEY")
        if springer:
            out.append(SourceCandidate(
                url=(SPRINGER_OA_JATS + "?q=doi:" + quote(doi)
                     + "&api_key=" + quote(springer)),
                source="springer_oa", kind="fulltext_xml",
            ))
        return out

    # -- One call that does all of it ---------------------------------------

    def locate(
        self,
        *,
        doi: Optional[str] = None,
        title: Optional[str] = None,
        first_author: Optional[str] = None,
        year: Optional[Any] = None,
    ) -> Tuple[List[SourceCandidate], Dict[str, Any]]:
        """Union of every locator that can say something, plus recovered ids.

        Callers merge this with the pre-existing Unpaywall / Semantic Scholar /
        Crossref results and rank the whole pool once.
        """
        doi = clean_doi(doi)
        candidates: List[SourceCandidate] = []
        meta: Dict[str, Any] = {}

        epmc_cands, epmc_meta = self.europepmc(
            doi=doi, title=title, first_author=first_author, year=year
        )
        candidates.extend(epmc_cands)
        meta.update({k: v for k, v in epmc_meta.items() if v})
        doi = doi or clean_doi(meta.get("doi"))

        oa_cands, oa_doi = self.openalex(doi=doi, title=title)
        candidates.extend(oa_cands)
        if oa_doi and not doi:
            doi = oa_doi
            meta.setdefault("doi", oa_doi)

        if doi and not meta.get("pmcid"):
            pmcid = self.pmcid_for_doi(doi)
            if pmcid:
                meta["pmcid"] = pmcid
                candidates.extend(self.pmc_fulltext(pmcid))

        if doi:
            candidates.extend(self.publisher_tdm(doi))

        # Long shots, only when everything above came up empty. arXiv costs
        # ~16 seconds per call (export.arxiv.org paces requests hard) and a
        # biomedical corpus is not on arXiv — paying that on every citation is
        # 13 minutes per run for nothing. As a last resort for the references
        # nothing else could place, it is worth the wait.
        if title and not candidates:
            candidates.extend(self.core(title, doi=doi))
            if not candidates:
                candidates.extend(self.arxiv(title))

        return candidates, meta
