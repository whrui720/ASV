"""Academic Paper Finder — resolves citations to downloadable URLs.

**Union-then-rank, not first-hit-wins** (SOURCE_ACQUISITION.md F1). The previous
cascade guarded every step with ``if not candidates``, so a single publisher URL
from Unpaywall shadowed Semantic Scholar, Crossref and Google Scholar — the
measured consequence being that 32 of 51 citation batches had exactly one
candidate URL and one 403 killed the batch outright.

Now every resolver that can cheaply say something is asked, the answers are
pooled, deduped, and sorted by how likely the bytes at that URL are to contain
the sentence we need to quote:

    full-text XML  >  repository PDF  >  repository landing
                   >  publisher PDF   >  publisher landing  >  search guess

The expensive resolvers (Google Scholar through a real browser) still run only
when the pool is thin, because they cost seconds rather than milliseconds.

Resolution is cached per citation string for the life of the process, which is
what makes the orchestrator's up-front resolution pass free: it resolves every
citation to decide which publishers need a login, and the per-batch calls that
follow are cache hits.

Cookie-based institutional auth remains as an escape hatch (see
``INSTITUTIONAL_COOKIES``), but the browser login flow and ``EZPROXY_HOST``
supersede it.
"""

import json
import logging
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from asv.core import credentials as creds

from .config import (
    CROSSREF_API,
    ENABLE_GOOGLE_SCHOLAR,
    DOWNLOAD_TIMEOUT,
    INSTITUTIONAL_COOKIES,
    MAX_RESOLUTION_CANDIDATES,
    SEMANTIC_SCHOLAR_API,
    SEMANTIC_SCHOLAR_API_KEY,
    THIN_CANDIDATE_POOL,
    UNPAYWALL_API,
    UNPAYWALL_EMAIL,
)
from .fulltext_apis import (
    FullTextAPIs,
    SourceCandidate,
    classify,
    clean_doi,
    extract_doi,
    rank_and_dedupe,
    title_matches,
)
from .polite_http import PoliteSession
from .reference_text import normalise_reference

logger = logging.getLogger(__name__)


class AcademicPaperFinder:
    """Resolves a raw citation string (or DOI) to a ranked candidate list.

    When ``llm_client`` is provided the finder parses bibliography-formatted
    strings into structured fields before searching, which matters enormously
    on real corpora: the test paper carries zero inline DOIs across 253
    references.
    """

    def __init__(self, llm_client=None):
        self.llm_client = llm_client
        self.browser_searcher = None  # injected by orchestrator after startup login
        self._session = PoliteSession(
            "ASV-pipeline/1.0 (academic source validation; "
            + (("mailto:" + creds.contact_email()) if creds.contact_email()
               else "contact via project repo")
            + ")",
            default_headers={"Accept": "application/json"},
        )
        # Sent per request, never on the session: this session also talks to
        # Crossref, Unpaywall, Europe PMC, OpenAlex and (via fetch_with_cookies)
        # arbitrary publisher hosts, none of which should see the key.
        self._s2_headers = (
            {"x-api-key": SEMANTIC_SCHOLAR_API_KEY} if SEMANTIC_SCHOLAR_API_KEY else {}
        )

        self.fulltext = FullTextAPIs(self._session)

        # Parse institutional cookies once at startup
        self._inst_cookies: Dict[str, Dict[str, str]] = {}
        if INSTITUTIONAL_COOKIES:
            try:
                self._inst_cookies = json.loads(INSTITUTIONAL_COOKIES)
                logger.info(
                    "Institutional cookies loaded for domains: %s",
                    list(self._inst_cookies.keys()),
                )
            except json.JSONDecodeError as e:
                logger.warning("INSTITUTIONAL_COOKIES is not valid JSON: %s", e)

        # Cache the LLM citation parse across batches so a batch of eight claims
        # sharing one citation parses it once.
        self._parse_cache: Dict[str, Dict[str, Any]] = {}
        # Cache the whole resolution, so the orchestrator's up-front pass over
        # every citation costs nothing when the batches come round again.
        self._resolution_cache: Dict[Tuple[str, str], List[SourceCandidate]] = {}
        #: Every host any citation resolved to. The paywall-login checkpoint
        #: reads this instead of grepping bibliography text for domain names
        #: that were never in it (F6).
        self.resolved_hosts: set[str] = set()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def find_url(self, raw_citation_text: str) -> Optional[str]:
        """Best single candidate URL, or None."""
        urls = self.find_urls(raw_citation_text)
        return urls[0] if urls else None

    def find_urls(
        self, raw_citation_text: str, known_doi: Optional[str] = None
    ) -> List[str]:
        """Ranked candidate URLs. Thin wrapper over :meth:`find_candidates`."""
        return [c.url for c in self.find_candidates(raw_citation_text, known_doi)]

    def find_candidates(
        self, raw_citation_text: str, known_doi: Optional[str] = None
    ) -> List[SourceCandidate]:
        """Pool every resolver's answer, dedupe, and rank.

        Ordering of the pool build matters only for tie-breaks within a kind;
        the kind itself decides the ordering, so an Unpaywall publisher landing
        page can no longer outrank a Europe PMC full-text mirror just because
        Unpaywall was asked first.
        """
        cache_key = (raw_citation_text or "", clean_doi(known_doi) or "")
        cached = self._resolution_cache.get(cache_key)
        if cached is not None:
            return list(cached)

        clean_text = normalise_reference(raw_citation_text)
        parsed = self._parse_citation_with_llm(clean_text)
        title = parsed.get("title")
        first_author = parsed.get("first_author")
        year = parsed.get("year")

        doi = (
            clean_doi(known_doi)
            or extract_doi(clean_text)
            or clean_doi(parsed.get("doi"))
        )
        if doi:
            logger.info("  DOI in hand: %s", doi)

        pool: List[SourceCandidate] = []

        # -- Tier 1: the services that actually hold open-access full text ---
        ft_candidates, ft_meta = self.fulltext.locate(
            doi=doi, title=title, first_author=first_author, year=year
        )
        pool.extend(ft_candidates)
        if not doi and ft_meta.get("doi"):
            doi = clean_doi(ft_meta["doi"])
            logger.info("  DOI recovered from Europe PMC/OpenAlex: %s", doi)

        # -- The pre-existing resolvers, now unioned rather than short-circuited
        if doi:
            pool.extend(self._try_unpaywall(doi))
            pool.extend(self._try_semantic_scholar_by_doi(doi))
            pool.extend(self._try_crossref(doi))

        if not doi:
            ss_urls, ss_doi = self._try_semantic_scholar_by_text(
                title or clean_text, expected_title=title
            )
            pool.extend(ss_urls)
            if ss_doi:
                doi = clean_doi(ss_doi)
                logger.info("  Semantic Scholar surfaced DOI: %s", doi)
                pool.extend(self._try_unpaywall(doi))
                pool.extend(self._try_crossref(doi))

        if not doi:
            cr_doi = clean_doi(self._resolve_doi_via_crossref(parsed, clean_text))
            if cr_doi:
                doi = cr_doi
                logger.info("  Crossref bibliographic surfaced DOI: %s", doi)
                pool.extend(self._try_unpaywall(doi))
                pool.extend(self._try_semantic_scholar_by_doi(doi))
                pool.extend(self._try_crossref(doi))
                # A DOI found this late has not been through the full-text
                # locators yet, and it is exactly the DOI-less reference those
                # locators help most.
                late, _ = self.fulltext.locate(doi=doi)
                pool.extend(late)

        # -- Last resort, in rank order ---------------------------------------
        # The DOI landing page. Deliberately last: it is usually a publisher
        # paywall, and with the content gate in place it yields an honest
        # ``abstract_only`` abstention rather than a fabricated verdict. It is
        # also the URL the EZproxy and browser phases can most often rescue.
        if doi:
            pool.append(SourceCandidate(
                url="https://doi.org/" + doi, source="doi_landing",
                kind="publisher_landing",
            ))

        ranked = rank_and_dedupe(pool, limit=MAX_RESOLUTION_CANDIDATES)

        # Google Scholar costs seconds and a browser tab, so it runs only when
        # the cheap resolvers left us with nothing worth trying — and only when
        # explicitly enabled (ASV_ENABLE_SCHOLAR), because it has never returned
        # a usable link on this corpus and now sits on the run's critical path.
        if (
            ENABLE_GOOGLE_SCHOLAR
            and len(ranked) < THIN_CANDIDATE_POOL
            and self.browser_searcher is not None
        ):
            scholar_query = self._build_scholar_query(parsed, clean_text)
            logger.info("  Thin candidate pool — trying Google Scholar: %r", scholar_query)
            try:
                for url in self.browser_searcher.search_google_scholar(scholar_query, top_k=3):
                    pool.append(SourceCandidate(
                        url=url, source="google_scholar", kind="search_guess",
                    ))
            except Exception as e:
                logger.warning("  Browser fallback failed: %s", e)
            ranked = rank_and_dedupe(pool, limit=MAX_RESOLUTION_CANDIDATES)

        for c in ranked:
            host = (urlparse(c.url).netloc or "").lower()
            if host:
                self.resolved_hosts.add(host)

        if ranked:
            logger.info(
                "  Resolved %d candidate(s); best is %s [%s]",
                len(ranked), ranked[0].url[:90], ranked[0].kind,
            )
        else:
            logger.info("  No URL found (all resolvers exhausted)")

        self._resolution_cache[cache_key] = ranked
        return list(ranked)

    # ------------------------------------------------------------------
    # LLM-based citation parsing
    # ------------------------------------------------------------------

    def _parse_citation_with_llm(self, raw_text: str) -> Dict[str, Any]:
        """Parse a bibliography string into ``{title, first_author, year, journal, doi, type}``.

        Cached per input string so batched claims sharing one citation parse
        once. Returns ``{}`` when no LLM is wired up or the call fails — every
        caller handles missing fields.
        """
        if not raw_text:
            return {}
        raw_text = normalise_reference(raw_text)
        if raw_text in self._parse_cache:
            return self._parse_cache[raw_text]
        if self.llm_client is None:
            self._parse_cache[raw_text] = {}
            return {}

        prompt = (
            "Parse the following bibliography citation into structured fields. "
            "Return JSON with keys: title, first_author, year, journal, volume, "
            "first_page, last_page, doi, type. "
            "Use null for any field you cannot determine. The title should be the "
            "paper/article title only (no author or journal). first_author is the "
            "surname of the first listed author. year is a 4-digit integer or null. "
            "type is one of: journal-article, book, chapter, conference-paper, "
            "conference-abstract, preprint, dataset, thesis, report, webpage, "
            "personal-communication.\n"
            "Reference strings extracted from PDFs often lose the spaces at field "
            "boundaries (e.g. 'J Virol1999; 73: 2181' means journal 'J Virol', year "
            "1999, volume 73, first page 2181) — split them correctly.\n\n"
            "Citation: " + raw_text + "\n\n"
            'Example output: {"title": "Gene delivery using herpes simplex virus vectors", '
            '"first_author": "Burton", "year": 2002, "journal": "DNA Cell Biol", '
            '"volume": "21", "first_page": "915", "last_page": "936", "doi": null, '
            '"type": "journal-article"}'
        )
        try:
            result = self.llm_client.call_llm(
                prompt,
                response_format="json",
                task_name="reference_parsing",
                system_message="You parse academic citation strings into structured fields.",
            )
            if not isinstance(result, dict):
                result = {}
        except Exception as e:
            logger.debug("  Citation parse failed: %s", e)
            result = {}

        self._parse_cache[raw_text] = result
        return result

    def _resolve_doi_via_crossref(
        self, parsed: Dict[str, Any], raw_fallback: str
    ) -> Optional[str]:
        """Crossref bibliographic search, with a sanity check on the hit.

        Crossref always returns *something* for a bibliographic query, so taking
        the top row unconditionally is how a reference to a 1982 Cell paper ends
        up resolving to an unrelated 2019 review. The returned title has to look
        like the one we asked for before we believe it.
        """
        params: Dict[str, Any] = {"rows": 3}
        if creds.contact_email():
            params["mailto"] = creds.contact_email()

        title = parsed.get("title")
        if title:
            # Structured fields beat one blob: Crossref scores them separately
            # and the author/container constraints throw out near-title matches
            # from the wrong journal (F8).
            params["query.bibliographic"] = title
            if parsed.get("first_author"):
                params["query.author"] = str(parsed["first_author"])
            if parsed.get("journal"):
                params["query.container-title"] = str(parsed["journal"])
        else:
            params["query.bibliographic"] = raw_fallback[:200]

        try:
            resp = self._session.get(
                "https://api.crossref.org/works", params=params, timeout=DOWNLOAD_TIMEOUT
            )
            if resp.status_code >= 400:
                return None
            items = resp.json().get("message", {}).get("items", [])
        except Exception as e:
            logger.debug("  Crossref bibliographic error: %s", e)
            return None

        for item in items:
            if not title:
                return item.get("DOI")
            candidate_title = (item.get("title") or [""])[0]
            if title_matches(title, candidate_title):
                return item.get("DOI")
            logger.debug(
                "  Crossref top hit rejected (title mismatch): %r vs %r",
                title[:60], candidate_title[:60],
            )
        return None

    @staticmethod
    def _build_scholar_query(parsed: Dict[str, Any], raw_fallback: str) -> str:
        """Compose a Scholar-friendly query from parsed fields; fall back to raw text."""
        title = parsed.get("title")
        author = parsed.get("first_author")
        year = parsed.get("year")
        if title:
            parts = ['"' + str(title) + '"']
            if author:
                parts.append(str(author))
            if year:
                parts.append(str(year))
            return " ".join(parts)
        return raw_fallback[:200]

    def fetch_with_cookies(self, url: str, timeout: int = DOWNLOAD_TIMEOUT) -> Optional[bytes]:
        """Download *url* using institutional cookies for the matching domain.

        Matching is now suffix-based: the old exact-netloc lookup meant a
        ``nature.com`` entry silently missed every ``www.nature.com`` URL (F5).
        """
        domain = (urlparse(url).netloc or "").lower()
        cookies: Dict[str, str] = {}
        for host, jar in self._inst_cookies.items():
            host = host.lower().lstrip(".")
            if domain == host or domain.endswith("." + host):
                cookies.update(jar)
        if not cookies:
            logger.debug("No institutional cookies configured for %s", domain)
            return None

        try:
            logger.info("  Trying institutional cookies for %s ...", domain)
            resp = self._session.get(
                url, cookies=cookies, timeout=timeout, browser_headers=True,
            )
            resp.raise_for_status()
            ct = resp.headers.get("content-type", "")
            if "text/html" in ct and b"login" in resp.content[:4096].lower():
                logger.warning("  Cookies present but server returned a login page — may be expired")
                return None
            logger.info("  ✓ Institutional download succeeded (%d bytes)", len(resp.content))
            return resp.content
        except Exception as e:
            logger.warning("  Institutional cookie fetch failed: %s", e)
            return None

    # ------------------------------------------------------------------
    # Individual resolvers
    # ------------------------------------------------------------------

    def _try_unpaywall(self, doi: str) -> List[SourceCandidate]:
        """All Unpaywall OA locations, each tagged with its host type.

        Unpaywall's own ``host_type`` is authoritative here — it knows that a
        given URL is a repository deposit rather than the publisher's copy, and
        that is precisely the distinction the ranking turns on.
        """
        email = UNPAYWALL_EMAIL or creds.get("UNPAYWALL_EMAIL")
        if not email:
            logger.warning(
                "  UNPAYWALL_EMAIL is not set — skipping Unpaywall, the single "
                "largest source of open-access mirrors. Set it on the config page."
            )
            return []
        try:
            resp = self._session.get(
                UNPAYWALL_API + "/" + doi,
                params={"email": email},
                timeout=DOWNLOAD_TIMEOUT,
            )
            if resp.status_code >= 400:
                return []
            data = resp.json()
        except Exception as e:
            logger.debug("  Unpaywall error: %s", e)
            return []

        locations = list(data.get("oa_locations") or [])
        best = data.get("best_oa_location")
        if best and best not in locations:
            locations.insert(0, best)

        out: List[SourceCandidate] = []
        for loc in locations:
            if not isinstance(loc, dict):
                continue
            host_type = "repository" if loc.get("host_type") == "repository" else None
            pdf = loc.get("url_for_pdf")
            if pdf:
                out.append(SourceCandidate(
                    url=pdf, source="unpaywall",
                    kind=classify(pdf, is_pdf=True, host_type=host_type),
                ))
            landing = loc.get("url_for_landing_page") or loc.get("url")
            if landing:
                out.append(SourceCandidate(
                    url=landing, source="unpaywall",
                    kind=classify(landing, is_pdf=False, host_type=host_type),
                ))
        if out:
            logger.debug("  Unpaywall: %d candidate(s)", len(out))
        return out

    def _try_semantic_scholar_by_doi(self, doi: str) -> List[SourceCandidate]:
        try:
            resp = self._session.get(
                SEMANTIC_SCHOLAR_API + "/paper/DOI:" + doi,
                params={"fields": "openAccessPdf,externalIds"},
                headers=self._s2_headers,
                timeout=DOWNLOAD_TIMEOUT,
            )
            if resp.status_code >= 400:
                return []
            url = (resp.json().get("openAccessPdf") or {}).get("url")
        except Exception as e:
            logger.debug("  Semantic Scholar (DOI) error: %s", e)
            return []
        if not url:
            return []
        return [SourceCandidate(
            url=url, source="semantic_scholar", kind=classify(url, is_pdf=True),
        )]

    def _try_crossref(self, doi: str) -> List[SourceCandidate]:
        """PDF links the publisher registered with Crossref.

        The DOI landing URL (``message.URL``) is not taken from here — it is
        appended once, last, by ``find_candidates``, so it cannot displace a
        repository mirror.
        """
        try:
            resp = self._session.get(CROSSREF_API + "/" + doi, timeout=DOWNLOAD_TIMEOUT)
            if resp.status_code >= 400:
                return []
            data = resp.json()
        except Exception as e:
            logger.debug("  Crossref error: %s", e)
            return []

        out: List[SourceCandidate] = []
        for link in data.get("message", {}).get("link", []):
            ct = link.get("content-type", "")
            u = link.get("URL")
            if u and ("pdf" in ct or "pdf" in u.lower()):
                out.append(SourceCandidate(
                    url=u, source="crossref", kind=classify(u, is_pdf=True),
                ))
        return out

    def _try_semantic_scholar_by_text(
        self, raw_text: str, expected_title: Optional[str] = None
    ) -> Tuple[List[SourceCandidate], Optional[str]]:
        """Title search. Returns candidates plus any DOI recovered along the way —
        the DOI is useful even when no OA PDF exists, because the other resolvers
        are all DOI-keyed."""
        if not raw_text or len(raw_text) < 10:
            return [], None
        try:
            resp = self._session.get(
                SEMANTIC_SCHOLAR_API + "/paper/search",
                params={
                    "query": raw_text[:150],
                    "fields": "title,openAccessPdf,externalIds",
                    "limit": 3,
                },
                headers=self._s2_headers,
                timeout=DOWNLOAD_TIMEOUT,
            )
            if resp.status_code >= 400:
                return [], None
            data = resp.json()
        except Exception as e:
            logger.debug("  Semantic Scholar (text) error: %s", e)
            return [], None

        recovered: Optional[str] = None
        out: List[SourceCandidate] = []
        for paper in data.get("data", []):
            # Only trust a recovered DOI when the row is plausibly the same
            # work. Everything downstream is DOI-keyed, so a wrong one here
            # ends with a claim judged against the wrong paper.
            same_work = title_matches(expected_title or raw_text, paper.get("title"))
            ext = paper.get("externalIds") or {}
            if recovered is None and ext.get("DOI") and same_work:
                recovered = ext["DOI"]
            url = (paper.get("openAccessPdf") or {}).get("url")
            if url and same_work:
                out.append(SourceCandidate(
                    url=url, source="semantic_scholar", kind=classify(url, is_pdf=True),
                ))
        return out, recovered

