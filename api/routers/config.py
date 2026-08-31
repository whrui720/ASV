"""Config/health: which API keys are present (booleans only, never values) and
the validator/sourcefinder thresholds currently in effect."""

from __future__ import annotations

import os

from fastapi import APIRouter

from api.schemas import ConfigStatus
from sourcefinder.config import DATASET_REUSE_THRESHOLD, DOWNLOAD_TIMEOUT, MAX_FILE_SIZE_MB
from validator.config import (
    DATASET_REUSE_CONFIDENCE,
    LLM_VERIFIER_CONFIDENCE_THRESHOLD,
    RAG_SIMILARITY_THRESHOLD,
    RAG_TOP_K,
    SCRIPT_TIMEOUT_SECONDS,
    TRUTH_TABLE_CONFIDENCE_THRESHOLD,
)

router = APIRouter(prefix="/api", tags=["config"])


@router.get("/config", response_model=ConfigStatus)
def get_config() -> ConfigStatus:
    env_keys = {
        "GEMINI_API_KEY": bool(os.getenv("GEMINI_API_KEY")),
        "GOOGLE_FACT_CHECK_API_KEY": bool(os.getenv("GOOGLE_FACT_CHECK_API_KEY")),
        "UNPAYWALL_EMAIL": bool(os.getenv("UNPAYWALL_EMAIL")),
        "SEMANTIC_SCHOLAR_API_KEY": bool(os.getenv("SEMANTIC_SCHOLAR_API_KEY")),
        "KAGGLE_USERNAME": bool(os.getenv("KAGGLE_USERNAME")),
        "KAGGLE_KEY": bool(os.getenv("KAGGLE_KEY")),
        "INSTITUTIONAL_COOKIES": bool(os.getenv("INSTITUTIONAL_COOKIES")),
    }
    thresholds = {
        "TRUTH_TABLE_CONFIDENCE_THRESHOLD": TRUTH_TABLE_CONFIDENCE_THRESHOLD,
        "LLM_VERIFIER_CONFIDENCE_THRESHOLD": LLM_VERIFIER_CONFIDENCE_THRESHOLD,
        "DATASET_REUSE_CONFIDENCE": DATASET_REUSE_CONFIDENCE,
        "RAG_TOP_K": RAG_TOP_K,
        "RAG_SIMILARITY_THRESHOLD": RAG_SIMILARITY_THRESHOLD,
        "SCRIPT_TIMEOUT_SECONDS": SCRIPT_TIMEOUT_SECONDS,
        "DATASET_REUSE_THRESHOLD": DATASET_REUSE_THRESHOLD,
        "MAX_FILE_SIZE_MB": MAX_FILE_SIZE_MB,
        "DOWNLOAD_TIMEOUT": DOWNLOAD_TIMEOUT,
    }
    return ConfigStatus(env_keys=env_keys, thresholds=thresholds)
