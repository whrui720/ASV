"""Configuration for sourcefinder tools"""

# API Keys
KAGGLE_USERNAME = None  # Set from env
KAGGLE_KEY = None  # Set from env

# Data repository endpoints
DATA_GOV_API = "https://catalog.data.gov/api/3/action/package_search"
KAGGLE_API_BASE = "https://www.kaggle.com/api/v1"

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
