"""Shared fixtures for the sourcefinder tests.

Two guards apply to every test in this package except those marked ``live``:

* **No network.** ``requests.Session.request`` is replaced with a recorder that
  refuses, and the test fails at teardown if anything tried. The clients under
  test catch every exception and return "no results", so without the teardown
  check an accidental live call would pass silently offline and flake online.
* **No real credentials.** ``credentials.py`` loads the developer's ``.env`` at
  import, so without this a test's behaviour would depend on which keys the
  machine running it happens to have. Every catalogue credential is cleared,
  along with the module-level snapshots some clients take at import. Use the
  ``creds`` fixture to set the ones a test needs.
"""

from __future__ import annotations

import pytest
import requests

from asv.core.credentials import CREDENTIAL_SPECS

from .api_fakes import FakeHttp

# Module-level constants captured from the environment at import time. Clearing
# the environment does not reach these, so they are patched alongside it.
_SNAPSHOTS = {
    "UNPAYWALL_EMAIL": [
        ("asv.sourcefinder.academic_paper_finder", "UNPAYWALL_EMAIL"),
    ],
    "SEMANTIC_SCHOLAR_API_KEY": [
        ("asv.sourcefinder.academic_paper_finder", "SEMANTIC_SCHOLAR_API_KEY"),
    ],
    "PUBMED_API_KEY": [
        ("asv.sourcefinder.index_clients", "PUBMED_API_KEY"),
    ],
    "KAGGLE_USERNAME": [
        ("asv.sourcefinder.dataset_finder", "KAGGLE_USERNAME"),
    ],
    "KAGGLE_KEY": [
        ("asv.sourcefinder.dataset_finder", "KAGGLE_KEY"),
    ],
}

_EXTRA_ENV = ("ASV_CONTACT_EMAIL",)


def _is_live(request) -> bool:
    return request.node.get_closest_marker("live") is not None


@pytest.fixture(autouse=True)
def _no_network(request, monkeypatch):
    if _is_live(request):
        yield
        return
    attempts = []

    def refuse(self, method, url, *args, **kwargs):
        attempts.append(f"{method} {url}")
        raise requests.ConnectionError(f"offline test attempted network access: {method} {url}")

    monkeypatch.setattr(requests.Session, "request", refuse)
    yield
    assert not attempts, f"test reached the network: {attempts}"


class _Creds:
    def __init__(self, monkeypatch):
        self._mp = monkeypatch

    def set(self, **values: str) -> None:
        import importlib
        for name, value in values.items():
            self._mp.setenv(name, value)
            for module, attr in _SNAPSHOTS.get(name, ()):
                self._mp.setattr(importlib.import_module(module), attr, value)


@pytest.fixture(autouse=True)
def creds(request, monkeypatch):
    """Clears every credential; ``creds.set(NAME=value)`` turns one back on."""
    if _is_live(request):
        yield None
        return
    import importlib
    for name in [s.name for s in CREDENTIAL_SPECS] + list(_EXTRA_ENV):
        monkeypatch.delenv(name, raising=False)
    for targets in _SNAPSHOTS.values():
        for module, attr in targets:
            monkeypatch.setattr(importlib.import_module(module), attr, "")
    yield _Creds(monkeypatch)


# ---------------------------------------------------------------------------
# Live tests: a throttled service is "unavailable", not "changed shape"
# ---------------------------------------------------------------------------

_THROTTLED = pytest.StashKey[list]()


@pytest.fixture(autouse=True)
def _record_throttling(request, monkeypatch):
    """Under ``live``, note every 429 and timeout the real session sees.

    The clients swallow both and return "no results", which is indistinguishable
    from a changed response shape. NCBI and arXiv in particular throttle by IP
    for minutes at a time, so without this the live suite fails for reasons
    that say nothing about the contract.
    """
    if not _is_live(request):
        yield
        return
    from urllib.parse import urlparse

    from asv.sourcefinder import polite_http

    seen = request.node.stash.setdefault(_THROTTLED, [])
    real_get = polite_http.PoliteSession.get

    def spy(self, url, **kwargs):
        host = urlparse(url).netloc
        try:
            resp = real_get(self, url, **kwargs)
        except (requests.Timeout, polite_http.HostUnavailable) as e:
            seen.append(f"{host} ({type(e).__name__})")
            raise
        if resp.status_code == 429:
            seen.append(f"{host} (HTTP 429)")
        return resp

    monkeypatch.setattr(polite_http.PoliteSession, "get", spy)
    yield


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    throttled = item.stash.get(_THROTTLED, None)
    if report.when == "call" and report.failed and throttled:
        report.outcome = "skipped"
        report.longrepr = (
            str(item.path), item.location[1] or 0,
            "Skipped: service unavailable, not a contract failure: "
            + ", ".join(sorted(set(throttled))),
        )


@pytest.fixture
def fake_http():
    """A ``FakeHttp``; fails the test if any request matched no route."""
    fake = FakeHttp()
    yield fake
    assert not fake.unrouted, "unrouted requests: " + ", ".join(
        f"{c.method} {c.url} {c.params}" for c in fake.unrouted
    )
