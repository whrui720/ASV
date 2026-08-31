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
