"""Configuration for hybrid_sourcefinder module"""

import os
from pathlib import Path

# Output directories
DEFAULT_OUTPUT_DIR = "./treated_claims"
DEFAULT_DATASET_DIR = "./treated_claims/datasets"
DEFAULT_TEXT_DIR = "./treated_claims/texts"

# API Keys (loaded from environment)
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')
GOOGLE_FACT_CHECK_KEY = os.getenv('GOOGLE_FACT_CHECK_KEY')
KAGGLE_USERNAME = os.getenv('KAGGLE_USERNAME')
KAGGLE_KEY = os.getenv('KAGGLE_KEY')

# LLM Configuration
DEFAULT_MODEL = "gpt-4o-mini"
MAX_RETRIES = 3
TIMEOUT_SECONDS = 30

# Search Configuration
DATASET_SEARCH_TOP_K = 5
RELEVANCE_THRESHOLD = 0.5  # Minimum relevance score to accept a dataset

# Truth Table Configuration
TRUTH_TABLE_CONFIDENCE_THRESHOLD = 0.5  # Minimum confidence for truth table results

# Download Configuration
DOWNLOAD_TIMEOUT = 30  # seconds
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'

# Data Sources
DATA_GOV_API_URL = "https://catalog.data.gov/api/3/action/package_search"
GOOGLE_FACT_CHECK_API_URL = "https://factchecktools.googleapis.com/v1alpha1/claims:search"

# Logging
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
