"""Configuration for sourcefinder tools"""

import os

# API Keys
KAGGLE_USERNAME = os.getenv("KAGGLE_USERNAME")
KAGGLE_KEY = os.getenv("KAGGLE_KEY")

# Open-access paper resolution
UNPAYWALL_EMAIL = os.getenv("UNPAYWALL_EMAIL", "")          # required by Unpaywall ToS
SEMANTIC_SCHOLAR_API_KEY = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "")  # optional, improves rate limits

# Institutional cookie auth (JSON string: {"domain": {"cookie_name": "value"}})
# Example: '{"www.jstor.org": {"SessionID": "abc123"}, "www.nature.com": {"access_token": "xyz"}}'
INSTITUTIONAL_COOKIES = os.getenv("INSTITUTIONAL_COOKIES", "")

# Data repository endpoints
DATA_GOV_API = "https://catalog.data.gov/api/3/action/package_search"
KAGGLE_API_BASE = "https://www.kaggle.com/api/v1"

# data.gov's CKAN API is gone. SOURCE_ACQUISITION.md F10 flagged it as "returned
# 404 throughout the 2026-06-22 run"; re-verified 2026-09-23 — /api/3/action/*,
# /api/1/search and /dataset.json all answer 404 from an API gateway that is not
# CKAN any more. Left off by default so it does not cost a round trip per claim;
# set ASV_ENABLE_DATA_GOV=1 to try it again once a working endpoint is known.
ENABLE_DATA_GOV = os.getenv("ASV_ENABLE_DATA_GOV", "0").strip().lower() in (
    "1", "true", "yes",
)

# ---------------------------------------------------------------------------
# Dataset registries — SOURCE_ACQUISITION.md §6 / F10. These replace the
# browser scrapes of the same three sites, which returned zero links 100% of
# the time because they are client-rendered SPAs and the scrape read the empty
# shell. All four are keyless JSON.
#
# Figshare's search is POST with a JSON body; the GET form 404s with a routing
# error that reads like "no results" if you are not watching for it.
# ---------------------------------------------------------------------------
ZENODO_API = "https://zenodo.org/api/records"
FIGSHARE_SEARCH_API = "https://api.figshare.com/v2/articles/search"
HUGGINGFACE_DATASETS_API = "https://huggingface.co/api/datasets"
DATACITE_SEARCH_API = "https://api.datacite.org/dois"

# Open-access API endpoints
UNPAYWALL_API = "https://api.unpaywall.org/v2"
SEMANTIC_SCHOLAR_API = "https://api.semanticscholar.org/graph/v1"
CROSSREF_API = "https://api.crossref.org/works"

# ---------------------------------------------------------------------------
# Resolution breadth — SOURCE_ACQUISITION.md F1.
# The cascade used to stop at the first resolver that returned anything, which
# left 32 of 51 batches with exactly one candidate URL. It now pools every
# resolver and ranks; these two numbers bound the cost of doing that.
# ---------------------------------------------------------------------------
#: How many ranked candidates a citation may carry out of resolution. Larger
#: than MAX_CANDIDATES_PER_BATCH on purpose — the downloader stops early on full
#: text, so a deeper list costs nothing when the first candidate works.
MAX_RESOLUTION_CANDIDATES = 10
#: Below this many candidates, the pool is thin enough to justify paying for a
#: browser-driven Google Scholar search — if Scholar is enabled at all.
THIN_CANDIDATE_POOL = 2

# Google Scholar, off by default. SOURCE_ACQUISITION.md F4 measured it returning
# "no candidate links found" on every query — it is a client-rendered page
# behind a consent/CAPTCHA interstitial, and Google is explicitly hostile to
# automation — and recommends retiring it or gating it behind an opt-in flag.
# Gated rather than deleted because it is the only route left for a reference no
# index carries. Now that resolution runs as an up-front pass over every
# citation, leaving it on would mean ~14 browser searches before the run starts,
# each one slow, CAPTCHA-prone, and historically fruitless.
ENABLE_GOOGLE_SCHOLAR = os.getenv("ASV_ENABLE_SCHOLAR", "0").strip().lower() in (
    "1", "true", "yes",
)

# ---------------------------------------------------------------------------
# Institutional access — SOURCE_ACQUISITION.md §7.
# EZproxy access is a hostname rewrite, not a cookie hack:
#   https://www.sciencedirect.com/…  ->  https://www-sciencedirect-com.PROXY/…
# Set EZPROXY_HOST to your library's proxy host to enable the rewrite phase.
# The rewritten URL is fetched through the *browser* context, so the user's SSO
# session applies and no credential is ever handled by ASV.
# ---------------------------------------------------------------------------
EZPROXY_HOST = os.getenv("EZPROXY_HOST", "").strip().strip("/")
#: Hard cap on proxied fetches per run. Bulk downloading through a library
#: proxy is exactly what gets institutional access suspended; the user remains
#: responsible for their library's terms.
EZPROXY_MAX_PER_RUN = int(os.getenv("EZPROXY_MAX_PER_RUN", "40") or 40)

# ---------------------------------------------------------------------------
# Tier 0.3 — content-quality classifier thresholds (content_quality.py).
# Starting points. Calibrate with scripts/calibrate_content_quality.py against
# hand labels before trusting them; the unsafe direction (abstract classified
# as full text) must stay at zero.
# ---------------------------------------------------------------------------
CQ_MIN_USABLE_CHARS = 200        # below this -> REJECTED (the pre-Tier-0 gate)
CQ_PAYWALL_MAX_CHARS = 8_000     # access-wall phrases only count on short pages
CQ_STRONG_IMRAD_SECTIONS = 3     # this many section headings -> full text, any length
CQ_WEAK_IMRAD_SECTIONS = 2       # this many, if corroborated by size/page count
CQ_FULL_TEXT_MIN_CHARS = 6_000   # corroborating size for the weak-structure case
CQ_ABSTRACT_MAX_CHARS = 4_000    # below this, without structure -> abstract only
CQ_REF_LINE_FRACTION = 0.5       # bibliography-dominated page -> abstract only

# Max candidate URLs tried per batch before keeping the best (Tier 0.3 §4.4).
MAX_CANDIDATES_PER_BATCH = 6

# ---------------------------------------------------------------------------
# Tier 0.6 — reference existence + retraction checking (reference_verifier.py).
# Every endpoint below is keyless. Crossref and OpenAlex route requests to a
# faster "polite pool" when a contact address is supplied, so we reuse
# UNPAYWALL_EMAIL (already collected) as the mailto value.
# ---------------------------------------------------------------------------
CROSSREF_WORKS_API = "https://api.crossref.org/works"
OPENALEX_API = "https://api.openalex.org/works"
EUROPEPMC_API = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
PUBMED_ESEARCH_API = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
PUBMED_ESUMMARY_API = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
PUBMED_ECITMATCH_API = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/ecitmatch.cgi"
DATACITE_API = "https://api.datacite.org/dois"

PUBMED_API_KEY = os.getenv("PUBMED_API_KEY", "")   # optional: raises 3 -> 10 req/s
ASV_CONTACT_EMAIL = os.getenv("ASV_CONTACT_EMAIL", "") or UNPAYWALL_EMAIL

REFCHECK_TIMEOUT = 20
REFCHECK_MIN_INTERVAL_SECONDS = 0.35   # per-host politeness floor
REFCHECK_MAX_CANDIDATES = 5            # rows requested per index

# Match scoring (reference_verifier.py). A reference is only reported as
# not-found when at least REFCHECK_MIN_INDEXES_FOR_NOT_FOUND indexes actually
# responded — an API outage must never read as an accusation of fabrication.
REFCHECK_VERIFIED_TITLE_SIM = 0.90
REFCHECK_AMBIGUOUS_TITLE_SIM = 0.70
REFCHECK_MIN_INDEXES_FOR_NOT_FOUND = 2
REFCHECK_YEAR_TOLERANCE = 1            # publication-year drift is real
REFCHECK_MIN_INDEXED_YEAR = 1970       # older work is patchily indexed

# Reference types that bibliographic indexes systematically do not carry.
# Reference [1] of the test corpus is a chapter in Harrison's Principles of
# Internal Medicine: real, fine, and not in Crossref. Routing these to
# "unindexed by design" is what stops the canonical false positive.
UNINDEXED_REFERENCE_TYPES = frozenset({
    "book", "chapter", "book-chapter", "personal_communication",
    "personal communication", "thesis", "dissertation", "report",
    "webpage", "website", "patent", "software-manual", "conference-abstract",
})

# Enable/disable the Tier 0.6 bibliography audit (on by default; it is free).
ENABLE_REFERENCE_CHECK = os.getenv("ASV_REFERENCE_CHECK", "1").strip().lower() not in (
    "0", "false", "no",
)

# Search parameters
DEFAULT_TOP_K = 5
MIN_RELEVANCE_SCORE = 0.6
DATASET_REUSE_THRESHOLD = 0.75  # LLM confidence threshold for reusing datasets

# Download settings
DOWNLOAD_TIMEOUT = 60
MAX_FILE_SIZE_MB = 500

# Output directories
DATASET_OUTPUT_DIR = "./datasets"
TEXT_OUTPUT_DIR = "./text_sources"

# Browser-based search (Playwright fallback when APIs are exhausted or hit a paywall)
BROWSER_HEADLESS = False  # must be False to support human login flow
BROWSER_SEARCH_TIMEOUT = 30_000  # ms per page load
KNOWN_PAYWALL_DOMAINS = [
    "jstor.org", "nature.com", "science.org", "springer.com",
    "wiley.com", "tandfonline.com", "sagepub.com", "elsevier.com",
    "sciencedirect.com", "cell.com", "nejm.org", "thelancet.com",
    "oup.com", "cambridge.org", "annualreviews.org",
]
GOOGLE_SCHOLAR_URL = "https://scholar.google.com/scholar?q="
ZENODO_SEARCH_URL = "https://zenodo.org/search?q="
FIGSHARE_SEARCH_URL = "https://figshare.com/search?q="
HUGGINGFACE_DATASETS_URL = "https://huggingface.co/datasets?search="
