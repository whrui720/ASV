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

# Open-access API endpoints
UNPAYWALL_API = "https://api.unpaywall.org/v2"
SEMANTIC_SCHOLAR_API = "https://api.semanticscholar.org/graph/v1"
CROSSREF_API = "https://api.crossref.org/works"

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
