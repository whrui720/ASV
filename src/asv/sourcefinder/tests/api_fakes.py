"""A scripted stand-in for ``PoliteSession``, for testing the API clients.

Every source-finding client — ``BibliographicIndexes``, ``FullTextAPIs``,
``AcademicPaperFinder``, ``DatasetFinder`` — talks to the network through one
``PoliteSession.get`` call. That is the seam: swap the session for a
``FakeHttp`` and each client's request building and response parsing can be
tested against recorded payloads with no network, no rate limiter and no cache.

``PoliteSession`` itself (retry, backoff, circuit breaker, cache keys) is
covered separately in ``test_polite_http.py``.

Fixtures under ``fixtures/api/`` are real responses captured from each service
and trimmed to the fields the parsers read plus their neighbours. When a live
contract test (``test_api_contracts_live.py``) starts failing, re-capture the
affected payload rather than editing it by hand.

Routing is first-match on URL prefix (plus an optional subset match on query
params), so register specific routes before general ones. A request nothing
matches is answered 404 *and* recorded in ``unrouted``; the ``fake_http``
fixture fails the test on any unrouted request, because every client here
swallows exceptions and a mis-built URL would otherwise read as "no results".
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

import requests

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "api"


def load_fixture(name: str) -> Any:
    """A fresh copy of a recorded payload — JSON decoded, anything else as text."""
    path = FIXTURE_DIR / name
    text = path.read_text(encoding="utf-8")
    return json.loads(text) if path.suffix == ".json" else text


@dataclass
class Call:
    method: str
    url: str
    params: Dict[str, Any] = field(default_factory=dict)
    headers: Dict[str, str] = field(default_factory=dict)
    json: Any = None
    kwargs: Dict[str, Any] = field(default_factory=dict)


ParamMatch = Union[Dict[str, Any], Callable[[Dict[str, Any]], bool], None]


@dataclass
class Route:
    method: str
    prefix: str
    params: ParamMatch
    status: int
    body: Any
    content_type: str
    raises: Optional[BaseException]

    def matches(self, method: str, url: str, params: Dict[str, Any]) -> bool:
        if method != self.method or not url.startswith(self.prefix):
            return False
        if self.params is None:
            return True
        if callable(self.params):
            return bool(self.params(params))
        return all(str(params.get(k)) == str(v) for k, v in self.params.items())


class FakeHttp:
    """Answers ``get`` / ``post`` from registered routes and records every call."""

    def __init__(self):
        self.routes: List[Route] = []
        self.calls: List[Call] = []
        self.unrouted: List[Call] = []
        self.headers: Dict[str, str] = {}
        self.cookies = requests.cookies.RequestsCookieJar()
        # DatasetFinder POSTs to Figshare through ``self.session.session.post``.
        self.session = self

    # -- registration -------------------------------------------------------

    def add(
        self,
        prefix: str,
        body: Any = None,
        *,
        fixture: Optional[str] = None,
        status: int = 200,
        params: ParamMatch = None,
        method: str = "GET",
        raises: Optional[BaseException] = None,
        content_type: Optional[str] = None,
    ) -> "FakeHttp":
        if fixture is not None:
            body = load_fixture(fixture)
        if content_type is None:
            content_type = "application/json" if isinstance(body, (dict, list)) else "text/plain"
        self.routes.append(Route(method, prefix, params, status, body, content_type, raises))
        return self

    # -- the PoliteSession surface ------------------------------------------

    def get(self, url: str, *, params=None, headers=None, **kwargs) -> requests.Response:
        return self._dispatch(Call("GET", url, dict(params or {}), dict(headers or {}), None, kwargs))

    def post(self, url: str, *, json=None, params=None, headers=None, **kwargs) -> requests.Response:
        return self._dispatch(Call("POST", url, dict(params or {}), dict(headers or {}), json, kwargs))

    # -- inspection ---------------------------------------------------------

    def calls_to(self, prefix: str) -> List[Call]:
        return [c for c in self.calls if c.url.startswith(prefix)]

    def hosts(self) -> List[str]:
        from urllib.parse import urlparse
        return [urlparse(c.url).netloc for c in self.calls]

    # -- internals ----------------------------------------------------------

    def _dispatch(self, call: Call) -> requests.Response:
        self.calls.append(call)
        for route in self.routes:
            if route.matches(call.method, call.url, call.params):
                if route.raises is not None:
                    raise route.raises
                return _response(call.url, route.status, copy.deepcopy(route.body), route.content_type)
        self.unrouted.append(call)
        return _response(call.url, 404, {"error": "unrouted in FakeHttp"}, "application/json")


def _response(url: str, status: int, body: Any, content_type: str) -> requests.Response:
    resp = requests.Response()
    resp.status_code = status
    resp.url = url
    resp.encoding = "utf-8"
    resp.headers["content-type"] = content_type
    if isinstance(body, (dict, list)):
        resp._content = json.dumps(body).encode("utf-8")
    elif isinstance(body, bytes):
        resp._content = body
    else:
        resp._content = (body or "").encode("utf-8")
    return resp
