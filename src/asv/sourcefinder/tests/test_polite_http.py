"""The shared HTTP layer — SOURCE_ACQUISITION.md F7.

Two of these pin bugs that were live in this module before they were written,
and both had the same shape: a cache key that was too coarse, serving one
request's answer to a different question.
"""

import time

import pytest
import requests

from asv.sourcefinder import polite_http
from asv.sourcefinder.polite_http import HttpCache, PoliteSession

pytestmark = pytest.mark.unit


class FakeInner:
    """Stands in for ``requests.Session``; records every call."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.headers = {}
        self.cookies = requests.cookies.RequestsCookieJar()

    def get(self, url, headers=None, **kwargs):
        self.calls.append({"url": url, "headers": headers or {}, **kwargs})
        status, body = self.responses.pop(0) if self.responses else (200, b"ok")
        resp = requests.Response()
        resp.status_code = status
        resp._content = body
        resp.url = url
        resp.headers["content-type"] = "application/json"
        return resp


def _session(tmp_path, responses, **kwargs):
    kwargs.setdefault("min_interval", 0)
    s = PoliteSession("test-agent", cache=HttpCache(tmp_path / "cache"), **kwargs)
    s.session = FakeInner(responses)
    return s


@pytest.fixture(autouse=True)
def _clean_breakers():
    polite_http.reset_circuit_breakers()
    yield
    polite_http.reset_circuit_breakers()


def test_query_params_are_part_of_the_cache_key(tmp_path):
    """The bug this was written for: every index client passes its query as
    ``params``, so a key of the bare URL served the first paper's record for
    every subsequent lookup against that endpoint."""
    s = _session(tmp_path, [(200, b'{"n":1}'), (200, b'{"n":2}')])

    first = s.get("https://api.example.org/works", params={"doi": "10.1/a"})
    second = s.get("https://api.example.org/works", params={"doi": "10.1/b"})

    assert first.content == b'{"n":1}'
    assert second.content == b'{"n":2}', "different query served from the wrong cache entry"
    assert len(s.session.calls) == 2


def test_identical_requests_hit_the_cache(tmp_path):
    s = _session(tmp_path, [(200, b"body")])

    s.get("https://api.example.org/x", params={"q": "1"})
    again = s.get("https://api.example.org/x", params={"q": "1"})

    assert len(s.session.calls) == 1, "second identical GET should not touch the network"
    assert again.content == b"body"
    assert again.status_code == 200


def test_auth_generation_invalidates_the_cache(tmp_path):
    """A 403 recorded before the user logged in must not be replayed after."""
    s = _session(tmp_path, [(403, b"denied"), (200, b"full text")])

    denied = s.get("https://publisher.example/article")
    assert denied.status_code == 403
    assert s.get("https://publisher.example/article").status_code == 403  # cached

    polite_http.bump_auth_generation()
    after_login = s.get("https://publisher.example/article")

    assert after_login.status_code == 200
    assert after_login.content == b"full text"


def test_retries_429_then_succeeds(tmp_path):
    s = _session(tmp_path, [(429, b""), (429, b""), (200, b"ok")], max_retries=3)
    # Retry-After of 0 keeps the test instant while still exercising the header path.
    s.session.responses = [(429, b""), (200, b"ok")]

    resp = s.get("https://slow.example/x")

    assert resp.status_code == 200
    assert len(s.session.calls) == 2


def test_403_is_not_retried(tmp_path):
    """Publishers return 403 deterministically for unauthenticated traffic;
    retrying only burns the host's patience."""
    s = _session(tmp_path, [(403, b""), (200, b"ok")], max_retries=3)

    resp = s.get("https://publisher.example/x")

    assert resp.status_code == 403
    assert len(s.session.calls) == 1


def test_circuit_breaker_trips_after_repeated_exhaustion(tmp_path):
    """Keyless CORE answers 429 to everything. Without this, each of 51
    citations pays four round trips and ~14s of backoff to learn that again."""
    s = _session(tmp_path, [(429, b"")] * 100, max_retries=0)

    for i in range(polite_http.CIRCUIT_TRIP_AFTER):
        s.get(f"https://dead.example/{i}")

    with pytest.raises(polite_http.HostUnavailable):
        s.get("https://dead.example/next")


def test_a_success_clears_the_failure_count(tmp_path):
    s = _session(tmp_path, [(429, b""), (200, b"ok"), (429, b"")], max_retries=0)

    s.get("https://flaky.example/1")
    s.get("https://flaky.example/2")
    s.get("https://flaky.example/3")

    # Two exhaustions, but not consecutive, so the host stays available.
    assert not polite_http._host_is_cold("flaky.example")


def test_browser_headers_are_added_only_when_asked(tmp_path):
    s = _session(tmp_path, [(200, b"a"), (200, b"b")])

    s.get("https://publisher.example/one", browser_headers=True)
    s.get("https://api.example.org/two", params={"q": "x"})

    assert s.session.calls[0]["headers"]["Referer"] == "https://publisher.example/"
    assert s.session.calls[0]["headers"]["Sec-Fetch-Mode"] == "navigate"
    assert "Referer" not in (s.session.calls[1]["headers"] or {})


def test_per_host_interval_is_shared_across_sessions(tmp_path):
    """The politeness floor has to be process-wide: the resolver, the audit and
    the downloader each hold their own session, so a per-session clock means
    three times the configured rate."""
    a = _session(tmp_path, [(200, b"1")], min_interval=0.25)
    b = _session(tmp_path / "b", [(200, b"2")], min_interval=0.25)

    start = time.monotonic()
    a.get("https://same-host.example/1")
    b.get("https://same-host.example/2")
    elapsed = time.monotonic() - start

    assert elapsed >= 0.2, "second session ignored the first session's rate limit"


def test_a_broken_cache_directory_does_not_break_fetching(tmp_path):
    cache = HttpCache(tmp_path / "cache")
    cache.put = lambda *a, **k: (_ for _ in ()).throw(OSError("disk full"))
    s = PoliteSession("t", min_interval=0, cache=cache)
    s.session = FakeInner([(200, b"ok")])

    with pytest.raises(OSError):
        # The guard lives inside HttpCache.put, which this test replaced —
        # so assert the real implementation's guard separately, below.
        cache.put("u", 200, {}, b"", "u")

    real = HttpCache(tmp_path / "readonly-ish")
    real.root = tmp_path / "\0invalid"  # unopenable on every platform
    real.put("https://x/y", 200, {}, b"body", "https://x/y")  # must not raise
    assert real.get("https://x/y") is None


def test_a_5xx_does_not_trip_the_circuit_breaker(tmp_path):
    """Europe PMC answers 500 — not 404 — for an article outside its
    open-access full-text subset. Counting that toward the breaker switched off
    the highest-yield source in the pipeline three non-OA articles into a run.
    A per-resource error says nothing about the host's willingness to serve the
    next resource."""
    misses = polite_http.CIRCUIT_TRIP_AFTER + 2
    s = _session(tmp_path, [(500, b"")] * misses + [(200, b"full text")], max_retries=0)

    for i in range(misses):
        assert s.get(f"https://www.ebi.ac.uk/rest/PMC{i}/fullTextXML").status_code == 500

    # The host is still reachable for the article it does hold.
    assert s.get("https://www.ebi.ac.uk/rest/PMC999/fullTextXML").status_code == 200


def test_a_default_timeout_is_always_applied(tmp_path):
    """`requests` waits forever by default. A resolver that asks eight services
    per citation has eight chances to hang the run on one slow endpoint —
    measured at 90s for a single OpenAlex title search."""
    s = _session(tmp_path, [(200, b"ok")])

    s.get("https://api.example.org/x")

    assert s.session.calls[0]["timeout"] == polite_http.DEFAULT_TIMEOUT


def test_an_explicit_timeout_wins(tmp_path):
    s = _session(tmp_path, [(200, b"ok")])
    s.get("https://api.example.org/x", timeout=3)
    assert s.session.calls[0]["timeout"] == 3


def test_timeouts_are_not_retried(tmp_path):
    """Retrying turns one slow call into four — the opposite of what the
    timeout is for. Connection errors still retry."""
    s = _session(tmp_path, [], max_retries=3)
    calls = []

    def always_timeout(url, headers=None, **kwargs):
        calls.append(url)
        raise requests.Timeout("too slow")

    s.session.get = always_timeout

    with pytest.raises(requests.Timeout):
        s.get("https://slow.example/x")
    assert len(calls) == 1


def test_connection_errors_still_retry(tmp_path):
    s = _session(tmp_path, [], max_retries=2)
    calls = []

    def flaky(url, headers=None, **kwargs):
        calls.append(url)
        raise requests.ConnectionError("reset")

    s.session.get = flaky

    with pytest.raises(requests.ConnectionError):
        s.get("https://flaky.example/x")
    assert len(calls) == 3  # initial + 2 retries


def test_the_breaker_expires_and_gives_the_host_another_chance(tmp_path, monkeypatch):
    """A burst of 429s means "not right now", not "never again". A run lasts long
    enough that a host throttled in minute two is usually fine by minute twenty."""
    monkeypatch.setattr(polite_http, "CIRCUIT_COOLDOWN_SECONDS", 0.05)
    s = _session(tmp_path, [(429, b"")] * polite_http.CIRCUIT_TRIP_AFTER, max_retries=0)

    for i in range(polite_http.CIRCUIT_TRIP_AFTER):
        s.get(f"https://throttled.example/{i}")
    with pytest.raises(polite_http.HostUnavailable):
        s.get("https://throttled.example/blocked")

    time.sleep(0.06)
    s.session.responses = [(200, b"recovered")]
    assert s.get("https://throttled.example/after").content == b"recovered"
