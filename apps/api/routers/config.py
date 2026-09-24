"""Config/health: which API keys are present (booleans only, never values) and
the validator/sourcefinder thresholds currently in effect."""

from __future__ import annotations

import os

from fastapi import APIRouter

from apps.api.schemas import ConfigStatus
from asv.sourcefinder.config import (
    CQ_ABSTRACT_MAX_CHARS,
    CQ_FULL_TEXT_MIN_CHARS,
    CQ_MIN_USABLE_CHARS,
    CQ_STRONG_IMRAD_SECTIONS,
    CQ_WEAK_IMRAD_SECTIONS,
    DATASET_REUSE_THRESHOLD,
    DOWNLOAD_TIMEOUT,
    ENABLE_REFERENCE_CHECK,
    MAX_CANDIDATES_PER_BATCH,
    MAX_FILE_SIZE_MB,
    REFCHECK_MIN_INDEXES_FOR_NOT_FOUND,
    REFCHECK_VERIFIED_TITLE_SIM,
)
from asv.validator.config import (
    DATASET_REUSE_CONFIDENCE,
    LLM_VERIFIER_CONFIDENCE_THRESHOLD,
    QUOTE_VERIFICATION_THRESHOLD,
    RAG_SIMILARITY_THRESHOLD,
    RAG_TOP_K,
    SCRIPT_TIMEOUT_SECONDS,
    SOURCE_VERIFICATION_PROMPT_VERSION,
)

router = APIRouter(prefix="/api", tags=["config"])


@router.get("/config", response_model=ConfigStatus)
def get_config() -> ConfigStatus:
    env_keys = {
        "GEMINI_API_KEY": bool(os.getenv("GEMINI_API_KEY")),
        # Tier 0.6 uses keyless indexes, but Crossref and OpenAlex route
        # requests to a faster pool when a contact address is supplied.
        "UNPAYWALL_EMAIL": bool(os.getenv("UNPAYWALL_EMAIL")),
        "PUBMED_API_KEY": bool(os.getenv("PUBMED_API_KEY")),
        "SEMANTIC_SCHOLAR_API_KEY": bool(os.getenv("SEMANTIC_SCHOLAR_API_KEY")),
        "KAGGLE_USERNAME": bool(os.getenv("KAGGLE_USERNAME")),
        "KAGGLE_KEY": bool(os.getenv("KAGGLE_KEY")),
        "INSTITUTIONAL_COOKIES": bool(os.getenv("INSTITUTIONAL_COOKIES")),
    }
    thresholds = {
        "LLM_VERIFIER_CONFIDENCE_THRESHOLD": LLM_VERIFIER_CONFIDENCE_THRESHOLD,
        # Tier 0.5
        "QUOTE_VERIFICATION_THRESHOLD": QUOTE_VERIFICATION_THRESHOLD,
        "SOURCE_VERIFICATION_PROMPT_VERSION": SOURCE_VERIFICATION_PROMPT_VERSION,
        # Tier 0.3
        "CQ_MIN_USABLE_CHARS": CQ_MIN_USABLE_CHARS,
        "CQ_FULL_TEXT_MIN_CHARS": CQ_FULL_TEXT_MIN_CHARS,
        "CQ_ABSTRACT_MAX_CHARS": CQ_ABSTRACT_MAX_CHARS,
        "CQ_STRONG_IMRAD_SECTIONS": CQ_STRONG_IMRAD_SECTIONS,
        "CQ_WEAK_IMRAD_SECTIONS": CQ_WEAK_IMRAD_SECTIONS,
        "MAX_CANDIDATES_PER_BATCH": MAX_CANDIDATES_PER_BATCH,
        # Tier 0.6
        "ENABLE_REFERENCE_CHECK": ENABLE_REFERENCE_CHECK,
        "REFCHECK_VERIFIED_TITLE_SIM": REFCHECK_VERIFIED_TITLE_SIM,
        "REFCHECK_MIN_INDEXES_FOR_NOT_FOUND": REFCHECK_MIN_INDEXES_FOR_NOT_FOUND,
        "DATASET_REUSE_CONFIDENCE": DATASET_REUSE_CONFIDENCE,
        "RAG_TOP_K": RAG_TOP_K,
        "RAG_SIMILARITY_THRESHOLD": RAG_SIMILARITY_THRESHOLD,
        "SCRIPT_TIMEOUT_SECONDS": SCRIPT_TIMEOUT_SECONDS,
        "DATASET_REUSE_THRESHOLD": DATASET_REUSE_THRESHOLD,
        "MAX_FILE_SIZE_MB": MAX_FILE_SIZE_MB,
        "DOWNLOAD_TIMEOUT": DOWNLOAD_TIMEOUT,
    }
    return ConfigStatus(env_keys=env_keys, thresholds=thresholds)
