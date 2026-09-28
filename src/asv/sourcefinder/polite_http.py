"""Shared HTTP layer for source acquisition — SOURCE_ACQUISITION.md F7.

Three things every outbound fetch in ``sourcefinder/`` now gets for free:

* **A per-host minimum interval**, shared process-wide rather than per-session.
  The measured 49% -> 31% acquisition decline across four identical runs on the
  same PDF was rate-limit accumulation: seven bursts at ``asm.org`` in a row,
  no delay, no backoff. A politeness floor that lived on one session would not
  have helped, because the resolver, the downloader and the index clients each
  hold their own.
* **Retry with backoff** on 429 and 5xx, honouring ``Retry-After``. A 403 is
  *not* retried — publishers return it deterministically for unauthenticated
  traffic, so retrying only burns the host's patience.
* **An on-disk response cache**, so a rerun of the same paper re-reads what it
  already fetched instead of re-hammering 51 publishers. This is what makes the
  acquisition rate reproducible enough to A/B test the rest of the fixes.

``PoliteSession`` deliberately mimics the slice of ``requests.Session`` the
callers use (``get``, ``headers``, ``cookies``) rather than subclassing it: the
cache path has to be able to answer without a socket, and returning a
synthesised ``Response`` from a subclassed ``send()`` is more surprising than
this.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Tunables. Environment-overridable because the right politeness for a 51-batch
# biomedical run is not the right politeness for a one-off debug fetch.
# --------------------------------------------------------------------------

def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


#: Minimum seconds between two requests to the same host, across every session.
DEFAULT_MIN_INTERVAL = _env_float("ASV_HTTP_MIN_INTERVAL", 1.0)
#: Retries for retryable statuses (429/5xx) and connection errors.
DEFAULT_MAX_RETRIES = _env_int("ASV_HTTP_MAX_RETRIES", 3)
#: Cap on a single backoff sleep, so a hostile ``Retry-After: 3600`` cannot
#: park the pipeline for an hour.
MAX_BACKOFF_SECONDS = _env_float("ASV_HTTP_MAX_BACKOFF", 30.0)
#: How long a cached 2xx stays fresh (default one week).
CACHE_TTL_SECONDS = _env_int("ASV_HTTP_CACHE_TTL", 7 * 24 * 3600)
#: How long a cached 4xx stays fresh. Short on purpose: caching a 403 makes a
#: rerun polite, but cementing it would hide credentials the user just added.
NEGATIVE_CACHE_TTL_SECONDS = _env_int("ASV_HTTP_NEGATIVE_CACHE_TTL", 3600)
#: Set ASV_HTTP_CACHE=0 to bypass the cache entirely.
CACHE_ENABLED = os.getenv("ASV_HTTP_CACHE", "1").strip().lower() not in ("0", "false", "no")
#: Applied to any GET whose caller did not set one. ``requests`` defaults to
#: waiting forever, and a resolver that asks eight services per citation has
#: eight chances to hang the whole run on one slow endpoint. Measured: an
#: OpenAlex ``title.search`` on the anonymous pool took **90 seconds** for a
#: single citation — a request nobody should wait that long for, and at 50
#: citations the difference between a four-minute pass and a ninety-minute one.
DEFAULT_TIMEOUT = _env_float("ASV_HTTP_TIMEOUT", 25.0)

RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
#: Statuses worth remembering so a rerun does not repeat a pointless fetch.
NEGATIVE_CACHE_STATUSES = frozenset({400, 401, 403, 404, 410})

#: For fetching pages meant for humans. Publishers gate on UA shape, so a
#: script-looking agent is an instant 403 at journals.asm.org and friends.
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def api_user_agent() -> str:
    """For calling JSON APIs, where the browser UA is actively harmful.

    Verified the hard way: ``zenodo.org/api/records`` returns 200 to a
    descriptive research agent and **403 to the Chrome string**. Crossref,
    OpenAlex and Unpaywall likewise route a contactable agent to their polite
    pool. Publishers want a browser; registries want to know who is calling.
    """
    from asv.core import credentials as creds

    email = creds.contact_email()
    return (
        "ASV-pipeline/1.0 (automated source validation; "
        + (("mailto:" + email) if email else "contact via project repo")
        + ")"
    )


def default_cache_dir() -> Path:
    """Where cached bodies live. Under the repo by default so a user can delete
    it without hunting through ``~/.cache``."""
    override = os.getenv("ASV_HTTP_CACHE_DIR")
    if override:
        return Path(override)
    return Path("runs") / "_cache" / "http"


# --------------------------------------------------------------------------
# Process-wide per-host clock
# --------------------------------------------------------------------------

_host_clock: Dict[str, float] = {}
_host_clock_lock = threading.Lock()

#: Hosts that refuse us this many times in a row are declared cold and fail fast
#: for the rest of the process. Keyless CORE answers 429 to literally every
#: request; without this, each of 51 citations pays four round trips and ~14s of
#: backoff to learn that again.
CIRCUIT_TRIP_AFTER = _env_int("ASV_HTTP_CIRCUIT_TRIP", 3)
_host_failures: Dict[str, int] = {}

#: Only these count toward the breaker. A 5xx deliberately does **not**: Europe
#: PMC answers 500 — not 404 — for an article outside its open-access full-text
#: subset, so counting 5xx tripped the breaker three non-OA articles into a run
#: and switched off the highest-yield source in the pipeline for everything
#: after it. A per-resource error says nothing about the host's willingness to
#: serve the next resource; only "you are asking too often" does.
CIRCUIT_STATUSES = frozenset({429})


class HostUnavailable(requests.RequestException):
    """Raised instead of re-contacting a host that has already given up on us."""


#: How long a tripped host stays skipped before it gets another chance. A
#: cooldown rather than a permanent kill: a burst of 429s means "not right now",
#: not "never again", and a run lasts long enough that a host throttled in
#: minute two is usually fine by minute twenty.
CIRCUIT_COOLDOWN_SECONDS = _env_float("ASV_HTTP_CIRCUIT_COOLDOWN", 300.0)
_host_cold_until: Dict[str, float] = {}


def _note_host_exhausted(host: str) -> None:
    with _host_clock_lock:
        _host_failures[host] = _host_failures.get(host, 0) + 1
        if _host_failures[host] >= CIRCUIT_TRIP_AFTER:
            _host_cold_until[host] = time.monotonic() + CIRCUIT_COOLDOWN_SECONDS
            logger.warning(
                "  %s has refused %d requests in a row — skipping it for %.0fs",
                host, _host_failures[host], CIRCUIT_COOLDOWN_SECONDS,
            )


def _note_host_ok(host: str) -> None:
    if _host_failures.get(host) or _host_cold_until.get(host):
        with _host_clock_lock:
            _host_failures.pop(host, None)
            _host_cold_until.pop(host, None)


def _host_is_cold(host: str) -> bool:
    until = _host_cold_until.get(host)
    if until is None:
        return False
    if time.monotonic() >= until:
        # Cooldown elapsed — give the host a clean slate and one more try.
        with _host_clock_lock:
            _host_cold_until.pop(host, None)
            _host_failures.pop(host, None)
        return False
    return True


def reset_circuit_breakers() -> None:
    """Forget every tripped host. For tests, and for a retry the user asked for."""
    with _host_clock_lock:
        _host_failures.clear()
        _host_cold_until.clear()


#: Folded into every cache key. Bumping it makes the whole cache miss once.
#:
#: Session-level cookies are not part of a cache key — they live in the jar, not
#: in the call — so without this, the 403s recorded before the user logged in
#: would be replayed from disk *after* they logged in, and the manual login
#: would appear to do nothing. The orchestrator bumps this the moment it bridges
#: browser cookies into the HTTP sessions.
_auth_generation = 0


def bump_auth_generation() -> None:
    """Invalidate the response cache because our credentials just changed."""
    global _auth_generation
    _auth_generation += 1
    logger.info(
        "  HTTP cache invalidated (auth generation %d) — authenticated retries "
        "will not be served pre-login responses", _auth_generation,
    )
    reset_circuit_breakers()


#: Hosts whose published limit is stricter than ``DEFAULT_MIN_INTERVAL``.
#: Semantic Scholar keys get exactly 1 req/s across all endpoints and ask
#: clients to stay *below* it; pacing at 1.0s lets clock jitter produce a 429,
#: and a 429 counts toward the circuit breaker.
HOST_MIN_INTERVALS: Dict[str, float] = {
    "api.semanticscholar.org": 1.1,
}


def _wait_turn(host: str, min_interval: float) -> None:
    """Block until this host may be called again. Shared across all sessions."""
    if min_interval <= 0:
        return
    min_interval = max(min_interval, HOST_MIN_INTERVALS.get(host, 0.0))
    while True:
        with _host_clock_lock:
            now = time.monotonic()
            ready_at = _host_clock.get(host, 0.0)
            if now >= ready_at:
                _host_clock[host] = now + min_interval
                return
            wait = ready_at - now
        time.sleep(min(wait, min_interval))


# --------------------------------------------------------------------------
# Response cache
# --------------------------------------------------------------------------


class HttpCache:
    """Content-addressed GET cache: one ``.json`` of metadata, one ``.bin`` of body."""

    def __init__(self, root: Optional[Path] = None):
        self.root = Path(root) if root is not None else default_cache_dir()
        self._lock = threading.Lock()

    @staticmethod
    def _key(url: str, extra: str = "") -> str:
        return hashlib.sha256((url + "\n" + extra).encode("utf-8")).hexdigest()

    def _paths(self, key: str) -> tuple[Path, Path]:
        # Two-level fan-out keeps any one directory from growing to 10k entries.
        bucket = self.root / key[:2]
        return bucket / (key + ".json"), bucket / (key + ".bin")

    def get(self, url: str, extra: str = "") -> Optional[Dict[str, Any]]:
        key = self._key(url, extra)
        meta_path, body_path = self._paths(key)
        try:
            if not meta_path.exists() or not body_path.exists():
                return None
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            return None

        status = int(meta.get("status", 0))
        ttl = CACHE_TTL_SECONDS if status < 400 else NEGATIVE_CACHE_TTL_SECONDS
        if time.time() - float(meta.get("fetched_at", 0)) > ttl:
            return None
        try:
            meta["body"] = body_path.read_bytes()
        except Exception:
            return None
        return meta

    def put(
        self,
        url: str,
        status: int,
        headers: Dict[str, str],
        body: bytes,
        final_url: str,
        extra: str = "",
    ) -> None:
        key = self._key(url, extra)
        meta_path, body_path = self._paths(key)
        payload = {
            "url": url,
            "final_url": final_url,
            "status": status,
            "headers": {k.lower(): v for k, v in dict(headers).items()},
            "fetched_at": time.time(),
            "bytes": len(body),
        }
        try:
            with self._lock:
                meta_path.parent.mkdir(parents=True, exist_ok=True)
                body_path.write_bytes(body)
                meta_path.write_text(json.dumps(payload), encoding="utf-8")
        except Exception as e:  # a cache that cannot write must not break a fetch
            logger.debug("  HTTP cache write failed for %s: %s", url, e)


def _response_from_cache(meta: Dict[str, Any]) -> requests.Response:
    """Rebuild a ``requests.Response`` from cached bytes so callers cannot tell."""
    resp = requests.Response()
    resp.status_code = int(meta.get("status", 200))
    resp._content = meta.get("body", b"")  # type: ignore[attr-defined]
    resp.url = meta.get("final_url") or meta.get("url") or ""
    resp.headers.update(meta.get("headers") or {})
    resp.encoding = resp.encoding or "utf-8"
    return resp


# --------------------------------------------------------------------------
# The session
# --------------------------------------------------------------------------


class PoliteSession:
    """A rate-limited, retrying, caching ``requests.Session`` wrapper.

    Exposes ``headers`` and ``cookies`` straight through to the wrapped session
    so the orchestrator's cookie bridge — which injects the user's Playwright
    login into every HTTP client in the pipeline — keeps working unchanged.
    """

    def __init__(
        self,
        user_agent: str = BROWSER_UA,
        *,
        min_interval: float = DEFAULT_MIN_INTERVAL,
        max_retries: int = DEFAULT_MAX_RETRIES,
        cache: Optional[HttpCache] = None,
        use_cache: bool = True,
        default_headers: Optional[Dict[str, str]] = None,
    ):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = user_agent
        if default_headers:
            self.session.headers.update(default_headers)
        self.min_interval = min_interval
        self.max_retries = max_retries
        self._use_cache = use_cache and CACHE_ENABLED
        self.cache = cache if cache is not None else (HttpCache() if self._use_cache else None)

    # -- the requests.Session surface the pipeline actually uses ------------

    @property
    def headers(self):
        return self.session.headers

    @property
    def cookies(self):
        return self.session.cookies

    # -- the one verb we need ----------------------------------------------

    def get(
        self,
        url: str,
        *,
        cache: Optional[bool] = None,
        browser_headers: bool = False,
        referer: Optional[str] = None,
        **kwargs,
    ) -> requests.Response:
        """GET *url*, politely.

        ``browser_headers=True`` adds the ``Referer`` / ``Sec-Fetch-*`` set that
        a real navigation carries (F2 #3). Our User-Agent has always been
        browser-shaped, but everything around it said "script"; some publishers
        gate on exactly that mismatch.
        """
        host = urlparse(url).netloc
        use_cache = self._use_cache if cache is None else (cache and CACHE_ENABLED)
        # Anything that changes what comes back has to be part of the cache
        # identity. ``params`` above all: every index client passes its query
        # that way, so a key of the bare URL would serve one paper's record for
        # every lookup against that endpoint. Cookies matter for the same
        # reason in the other direction — an authenticated retry must not be
        # answered by the earlier anonymous 403 straight from disk.
        identity: list[str] = []
        if _auth_generation:
            identity.append("auth%d" % _auth_generation)
        if kwargs.get("params"):
            params_obj = kwargs["params"]
            items = (
                sorted(params_obj.items()) if isinstance(params_obj, dict)
                else sorted(params_obj)
            )
            identity.append(repr([(str(k), str(v)) for k, v in items]))
        if kwargs.get("cookies"):
            identity.append(repr(sorted(dict(kwargs["cookies"]).items())))
        extra = (
            hashlib.sha256("|".join(identity).encode()).hexdigest()[:32]
            if identity else ""
        )

        if use_cache and self.cache is not None:
            hit = self.cache.get(url, extra)
            if hit is not None:
                logger.debug("  HTTP cache hit (%s): %s", hit["status"], url)
                return _response_from_cache(hit)

        headers = dict(kwargs.pop("headers", None) or {})
        if browser_headers:
            headers.setdefault("Referer", referer or plausible_referer(url))
            headers.setdefault("Sec-Fetch-Dest", "document")
            headers.setdefault("Sec-Fetch-Mode", "navigate")
            headers.setdefault("Sec-Fetch-Site", "same-origin")
            headers.setdefault("Sec-Fetch-User", "?1")
            headers.setdefault("Upgrade-Insecure-Requests", "1")
        elif referer:
            headers.setdefault("Referer", referer)

        if _host_is_cold(host):
            raise HostUnavailable(
                host + " is rate-limiting every request; skipped for this run"
            )

        kwargs.setdefault("timeout", DEFAULT_TIMEOUT)

        last_exc: Optional[Exception] = None
        resp: Optional[requests.Response] = None
        exhausted = False
        for attempt in range(self.max_retries + 1):
            _wait_turn(host, self.min_interval)
            try:
                resp = self.session.get(url, headers=headers or None, **kwargs)
            except requests.Timeout:
                # Not retried. A service that did not answer inside the timeout
                # is unlikely to answer three more times, and retrying turns one
                # slow call into four — the opposite of what the timeout is for.
                logger.debug("  Timed out after %ss: %s", kwargs.get("timeout"), url)
                raise
            except requests.RequestException as e:
                # Connection resets and DNS blips are genuinely transient.
                last_exc = e
                if attempt >= self.max_retries:
                    _note_host_exhausted(host)
                    raise
                self._sleep_backoff(attempt, None)
                continue

            if resp.status_code in RETRYABLE_STATUSES:
                if attempt < self.max_retries:
                    logger.debug(
                        "  HTTP %s from %s — retry %s/%s",
                        resp.status_code, host, attempt + 1, self.max_retries,
                    )
                    self._sleep_backoff(attempt, resp.headers.get("Retry-After"))
                    continue
                exhausted = resp.status_code in CIRCUIT_STATUSES
            break

        if resp is None:  # pragma: no cover — the loop always raises or assigns
            raise last_exc or RuntimeError("GET " + url + " produced no response")

        if exhausted:
            _note_host_exhausted(host)
        else:
            _note_host_ok(host)

        if use_cache and self.cache is not None and (
            resp.status_code < 400 or resp.status_code in NEGATIVE_CACHE_STATUSES
        ):
            self.cache.put(
                url, resp.status_code, dict(resp.headers), resp.content,
                str(resp.url), extra,
            )
        return resp

    def stream_get(self, url: str, **kwargs) -> requests.Response:
        """A streaming GET: rate-limited and circuit-broken, but never cached.

        Datasets can be hundreds of megabytes, and the point of streaming them
        is to look at ``Content-Length`` and the first chunks before committing
        to the whole body — writing that into a response cache would defeat the
        size guard it exists to serve.
        """
        host = urlparse(url).netloc
        if _host_is_cold(host):
            raise HostUnavailable(
                host + " is rate-limiting every request; skipped for this run"
            )
        _wait_turn(host, self.min_interval)
        kwargs.setdefault("stream", True)
        kwargs.setdefault("timeout", DEFAULT_TIMEOUT)
        return self.session.get(url, **kwargs)

    @staticmethod
    def _sleep_backoff(attempt: int, retry_after: Optional[str]) -> None:
        delay = min(2.0 ** attempt, MAX_BACKOFF_SECONDS)
        if retry_after:
            try:
                delay = min(float(retry_after), MAX_BACKOFF_SECONDS)
            except ValueError:
                pass  # HTTP-date form; the exponential default is fine
        time.sleep(delay)


def plausible_referer(url: str) -> str:
    """The site's own root. A same-origin referer is what an in-site click sends."""
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return "https://scholar.google.com/"
    return parsed.scheme + "://" + parsed.netloc + "/"
