"""The credential catalogue — one declaration, used by the API, the UI and the docs.

SOURCE_ACQUISITION.md §3 lists what ASV asks the user for and notes that the
load-bearing ones fail *silently*: without ``UNPAYWALL_EMAIL`` the entire
Unpaywall step is skipped behind a ``logger.debug``, and the measured 31%
acquisition rate was recorded on a machine whose ``.env`` contained exactly one
line. A credential that is easy to forget and invisible when missing is a bug in
the product, not in the user.

So the catalogue below is data, not prose. ``apps/api/routers/config.py`` renders
it as a form, ``ConfigPage.tsx`` draws the inputs, and the pipeline reads the
same names out of the environment. Adding a credential means adding one entry
here.

**Where values go.** Writes land in the repo-root ``.env`` *and* in
``os.environ`` of the running API process. The ``.env`` write is the one that
matters: every pipeline run is a fresh subprocess (``job_manager.launch_run``)
that re-reads ``.env`` at import, so a key entered in the UI applies to the next
run without restarting the server. The ``os.environ`` update only keeps the
API's own ``/api/config`` view honest.

**What comes back out.** Never a secret. ``secret=True`` fields report presence
and a last-four hint; the rest (an email, a proxy hostname) round-trip their
value, because a user editing a typo in their own email address should be able
to see it.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import find_dotenv, load_dotenv

# Load ``.env`` here as well as in ``llm_config``. Both are idempotent, and
# whichever is imported first wins — which matters because reading a credential
# before anything happened to import the LLM config would silently see an unset
# variable and disable the feature it gates.
load_dotenv(find_dotenv(usecwd=True))

# Groups, in the order the UI should render them.
GROUP_CORE = "Core"
GROUP_OPEN_ACCESS = "Open access & indexes"
GROUP_PUBLISHER = "Publisher text-mining keys"
GROUP_INSTITUTIONAL = "Institutional access"
GROUP_DATA = "Data repositories"

GROUP_ORDER = [
    GROUP_CORE,
    GROUP_OPEN_ACCESS,
    GROUP_PUBLISHER,
    GROUP_INSTITUTIONAL,
    GROUP_DATA,
]

GROUP_BLURB = {
    GROUP_CORE: "Required for the pipeline to run at all.",
    GROUP_OPEN_ACCESS: (
        "Free, mostly keyless. These are the services that find an open-access "
        "mirror of a paywalled paper — the highest-yield thing on this page."
    ),
    GROUP_PUBLISHER: (
        "Free developer registrations whose terms permit text and data mining. "
        "Each one converts a class of 403s into full text: 80% of failed fetches "
        "are publishers blocking unauthenticated traffic."
    ),
    GROUP_INSTITUTIONAL: (
        "Your library's sanctioned access path. EZproxy is strongly preferred "
        "over pasting cookies; you stay responsible for your library's terms of use."
    ),
    GROUP_DATA: "Only needed for quantitative claims backed by tabular datasets.",
}


@dataclass(frozen=True)
class CredentialSpec:
    """One environment variable the user may need to supply."""

    name: str
    label: str
    group: str
    help: str
    #: Secrets never leave the server; everything else round-trips its value.
    secret: bool = True
    required: bool = False
    placeholder: str = ""
    #: Where to get it. Rendered as a link next to the field.
    signup_url: Optional[str] = None
    #: Free-text note about what breaks without it.
    impact: str = ""
    input_type: str = "text"  # "text" | "email" | "textarea"


CREDENTIAL_SPECS: List[CredentialSpec] = [
    # -- Core ---------------------------------------------------------------
    CredentialSpec(
        name="GEMINI_API_KEY",
        label="Gemini API key",
        group=GROUP_CORE,
        required=True,
        help="Primary LLM for claim extraction, citation parsing and verification.",
        signup_url="https://aistudio.google.com/apikey",
        impact="Nothing runs without this.",
        placeholder="AIza…",
    ),
    # -- Open access --------------------------------------------------------
    CredentialSpec(
        name="UNPAYWALL_EMAIL",
        label="Contact email (Unpaywall / Crossref / OpenAlex)",
        group=GROUP_OPEN_ACCESS,
        secret=False,
        input_type="email",
        help=(
            "Any real address, no signup. Unpaywall's terms require it, and "
            "Crossref and OpenAlex route requests carrying it to a faster "
            "'polite pool'."
        ),
        signup_url="https://unpaywall.org/products/api",
        impact=(
            "Disables two of the three Tier-1 resolvers. Unpaywall is skipped "
            "outright, and OpenAlex throttles its anonymous pool by delaying "
            "responses — measured at 90 seconds for one DOI lookup, versus under "
            "a second with an address — so ASV skips that too rather than stall "
            "the run. This is the highest-value field on the page."
        ),
        placeholder="you@university.edu",
    ),
    CredentialSpec(
        name="SEMANTIC_SCHOLAR_API_KEY",
        label="Semantic Scholar API key",
        group=GROUP_OPEN_ACCESS,
        help="Free, instant approval. Gives a dedicated rate limit.",
        signup_url="https://www.semanticscholar.org/product/api#api-key",
        impact="The shared anonymous pool returns 429 under a 50-batch run.",
    ),
    CredentialSpec(
        name="PUBMED_API_KEY",
        label="NCBI / PubMed API key",
        group=GROUP_OPEN_ACCESS,
        help="Free with an NCBI account. Raises PubMed from 3 to 10 requests/second.",
        signup_url="https://account.ncbi.nlm.nih.gov/settings/",
        impact="Slower bibliography audits and PMC full-text fetches without it.",
    ),
    CredentialSpec(
        name="CORE_API_KEY",
        label="CORE API key",
        group=GROUP_OPEN_ACCESS,
        help=(
            "Free key at core.ac.uk. CORE aggregates ~300M open-access papers "
            "from institutional repositories — the mirror layer that routes "
            "around publisher blocks."
        ),
        signup_url="https://core.ac.uk/services/api",
        impact="CORE still answers keyless but is aggressively rate-limited.",
    ),
    # -- Publisher TDM ------------------------------------------------------
    CredentialSpec(
        name="WILEY_TDM_TOKEN",
        label="Wiley TDM client token",
        group=GROUP_PUBLISHER,
        help=(
            "Free registration. Sent as the Wiley-TDM-Client-Token header against "
            "api.wiley.com."
        ),
        signup_url="https://onlinelibrary.wiley.com/library-info/resources/text-and-datamining",
        impact=(
            "Wiley is already telling us it wants this by name: our failed fetches "
            "come back '400 No TDM Client Token was found in the request'."
        ),
    ),
    CredentialSpec(
        name="ELSEVIER_API_KEY",
        label="Elsevier / ScienceDirect API key",
        group=GROUP_PUBLISHER,
        help="Free key at dev.elsevier.com. Sent as the X-ELS-APIKey header.",
        signup_url="https://dev.elsevier.com/apikey/manage",
        impact="Full-text XML for entitled content; abstracts otherwise.",
    ),
    CredentialSpec(
        name="ELSEVIER_INSTTOKEN",
        label="Elsevier institutional token",
        group=GROUP_PUBLISHER,
        help=(
            "Optional companion to the API key. Carries your institution's "
            "entitlement when the request does not originate from its IP range."
        ),
        signup_url="https://dev.elsevier.com/support.html",
        impact="Without it, off-campus Elsevier requests return abstracts only.",
    ),
    CredentialSpec(
        name="SPRINGER_API_KEY",
        label="Springer Nature API key",
        group=GROUP_PUBLISHER,
        help=(
            "Free key at dev.springernature.com. The open-access endpoint returns "
            "JATS full text."
        ),
        signup_url="https://dev.springernature.com/signup",
        impact=(
            "nature.com and link.springer.com are our most common 'successful' "
            "fetches — and they are abstract-only landing pages. This is the fix."
        ),
    ),
    # -- Institutional ------------------------------------------------------
    CredentialSpec(
        name="EZPROXY_HOST",
        label="Library EZproxy host",
        group=GROUP_INSTITUTIONAL,
        secret=False,
        help=(
            "Your library's proxy hostname. ASV rewrites blocked publisher URLs "
            "through it and retries in the logged-in browser, so your SSO session "
            "applies."
        ),
        signup_url="https://www.oclc.org/en/ezproxy.html",
        impact="Leaves publisher 403s unrecoverable except by manual login.",
        placeholder="proxy.lib.umich.edu",
    ),
    CredentialSpec(
        name="INSTITUTIONAL_COOKIES",
        label="Institutional cookies (escape hatch)",
        group=GROUP_INSTITUTIONAL,
        input_type="textarea",
        help=(
            'JSON of {"host": {"cookie": "value"}}. Superseded by the browser '
            "login flow and EZproxy — keep it for hosts neither can reach."
        ),
        impact="Nothing; the browser login flow does the same job and self-refreshes.",
        placeholder='{"www.jstor.org": {"SessionID": "…"}}',
    ),
    # -- Data ---------------------------------------------------------------
    CredentialSpec(
        name="KAGGLE_USERNAME",
        label="Kaggle username",
        group=GROUP_DATA,
        secret=False,
        help="From kaggle.com → Settings → API → Create New Token.",
        signup_url="https://www.kaggle.com/settings",
        impact="Kaggle dataset search is skipped.",
    ),
    CredentialSpec(
        name="KAGGLE_KEY",
        label="Kaggle API key",
        group=GROUP_DATA,
        help="The 'key' field of the kaggle.json token file.",
        signup_url="https://www.kaggle.com/settings",
        impact="Kaggle dataset search is skipped.",
    ),
]

SPECS_BY_NAME: Dict[str, CredentialSpec] = {s.name: s for s in CREDENTIAL_SPECS}


# ---------------------------------------------------------------------------
# .env reading and writing
# ---------------------------------------------------------------------------

def env_path() -> Path:
    """The repo-root ``.env``, which is what ``load_dotenv(find_dotenv(usecwd=True))``
    finds when the pipeline runs from the repo root."""
    override = os.getenv("ASV_ENV_FILE")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[3] / ".env"


_ASSIGN_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")


def _encode(value: str) -> str:
    """Quote a value when it contains anything dotenv would mis-parse."""
    if value == "":
        return ""
    if re.search(r'[\s#"\']', value):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return value


def read_env_file(path: Optional[Path] = None) -> Dict[str, str]:
    """Parse ``.env`` into a dict. Missing file reads as empty, not an error."""
    path = path or env_path()
    out: Dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = _ASSIGN_RE.match(line)
        if not m:
            continue
        out[m.group(1)] = _decode(m.group(2).strip())
    return out


def _decode(raw: str) -> str:
    """Inverse of :func:`_encode`.

    Has to walk the string rather than search for a closing quote: an
    ``INSTITUTIONAL_COOKIES`` value is JSON, so it is full of ``\\"`` and a
    naive ``raw.index('"', 1)`` truncates it at the first escaped quote.
    """
    if raw[:1] not in ("'", '"'):
        # Unquoted: an inline comment needs whitespace before the '#'.
        return raw.split(" #", 1)[0].strip()

    quote = raw[0]
    out: List[str] = []
    escaped = False
    for ch in raw[1:]:
        if escaped:
            out.append(ch)
            escaped = False
        elif ch == "\\" and quote == '"':
            escaped = True
        elif ch == quote:
            break
        else:
            out.append(ch)
    return "".join(out)


def write_env_values(values: Dict[str, str], path: Optional[Path] = None) -> List[str]:
    """Update ``.env`` in place, preserving comments, ordering and unknown keys.

    A key set to the empty string is removed rather than written blank, so
    clearing a field in the UI actually unsets it instead of leaving
    ``KEY=`` behind for ``os.getenv`` to return as a falsy-but-present value.

    Returns the names actually changed.
    """
    path = path or env_path()
    existing_lines = (
        path.read_text(encoding="utf-8", errors="replace").splitlines()
        if path.exists() else []
    )
    remaining = dict(values)
    changed: List[str] = []
    out: List[str] = []

    for line in existing_lines:
        m = _ASSIGN_RE.match(line)
        if not m or m.group(1) not in remaining:
            out.append(line)
            continue
        name = m.group(1)
        new_value = remaining.pop(name)
        if new_value == "":
            changed.append(name)
            continue  # drop the line entirely
        replacement = f"{name}={_encode(new_value)}"
        if replacement != line:
            changed.append(name)
        out.append(replacement)

    appended = [(k, v) for k, v in remaining.items() if v != ""]
    if appended:
        header = "# Added via the ASV config page"
        if header not in out:
            if out and out[-1].strip():
                out.append("")
            out.append(header)
        for name, value in appended:
            out.append(f"{name}={_encode(value)}")
            changed.append(name)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out).rstrip("\n") + "\n", encoding="utf-8")
    return changed


def apply_to_process(values: Dict[str, str]) -> None:
    """Mirror the write into this process's environment.

    Modules that snapshot ``os.getenv`` at import (``sourcefinder/config.py``)
    will not see this, which is fine: every run is a fresh subprocess. This only
    keeps the API's own status view from lying about what it just saved.
    """
    for name, value in values.items():
        if value == "":
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


def mask(value: Optional[str]) -> str:
    """A hint that identifies a secret without revealing it."""
    if not value:
        return ""
    if len(value) <= 8:
        return "•" * len(value)
    return "•" * 6 + value[-4:]


@dataclass
class CredentialState:
    """What the UI needs to render one field."""

    spec: CredentialSpec
    present: bool
    #: The real value for non-secret fields, a masked hint for secrets.
    display_value: str = ""
    #: True when the value came from the process environment rather than ``.env``
    #: — a shell export the config page cannot edit away.
    from_shell: bool = False


def current_state(path: Optional[Path] = None) -> List[CredentialState]:
    """Presence and display value for every catalogued credential."""
    file_values = read_env_file(path)
    states: List[CredentialState] = []
    for spec in CREDENTIAL_SPECS:
        value = os.getenv(spec.name) or file_values.get(spec.name) or ""
        states.append(CredentialState(
            spec=spec,
            present=bool(value),
            display_value=(mask(value) if spec.secret else value),
            from_shell=bool(os.getenv(spec.name)) and spec.name not in file_values,
        ))
    return states


# ---------------------------------------------------------------------------
# Accessors for the pipeline
# ---------------------------------------------------------------------------
#
# Read lazily rather than snapshotting at import, so a long-lived process that
# picks up a new key mid-session uses it.

def get(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def contact_email() -> str:
    """The address sent to Unpaywall, Crossref, OpenAlex and NCBI."""
    return get("ASV_CONTACT_EMAIL") or get("UNPAYWALL_EMAIL")


def auth_headers_for(url: str) -> Dict[str, str]:
    """Per-host authentication headers for a download.

    Keyed on host rather than attached to the candidate that produced the URL,
    so a Wiley TDM link still carries its token no matter which resolver
    surfaced it.
    """
    from urllib.parse import urlparse

    host = (urlparse(url).netloc or "").lower()
    headers: Dict[str, str] = {}
    if host.endswith("api.wiley.com"):
        token = get("WILEY_TDM_TOKEN")
        if token:
            headers["Wiley-TDM-Client-Token"] = token
    elif host.endswith("api.elsevier.com"):
        key = get("ELSEVIER_API_KEY")
        if key:
            headers["X-ELS-APIKey"] = key
        inst = get("ELSEVIER_INSTTOKEN")
        if inst:
            headers["X-ELS-Insttoken"] = inst
    return headers
