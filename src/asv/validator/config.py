"""Configuration for validator"""

import os

# Output directories
VALIDATION_OUTPUT_DIR = "./validation_results"
VALIDATION_SCRIPTS_DIR = "./validation_scripts"

# Validation thresholds
LLM_VERIFIER_CONFIDENCE_THRESHOLD = 0.8
DATASET_REUSE_CONFIDENCE = 0.75

# ---------------------------------------------------------------------------
# Tier 0.5 — evidence verification.
# An LLM can fabricate a quote, and a verdict whose quote is not really in the
# source is worthless ("checkable by a human in ten seconds" is the whole
# point). Quotes are matched against the retrieved excerpts after aggressive
# normalisation, so the threshold only has to absorb OCR/ligature noise.
# ---------------------------------------------------------------------------
QUOTE_VERIFICATION_THRESHOLD = 92   # rapidfuzz partial_ratio, 0-100
QUOTE_VERIFICATION_MIN_CHARS = 20   # shorter "quotes" match anything; reject them

# Recorded on every result so a verdict can be tied to the prompt that produced
# it (VALUE_PROPOSITION.md §10: LLM nondeterminism undermining the audit trail).
SOURCE_VERIFICATION_PROMPT_VERSION = "2026-09-15.tier0"

# LLM settings
LLM_TEMPERATURE = 0.2
LLM_MAX_RETRIES = 3

# RAG settings
RAG_TOP_K = 3
RAG_TOP_K_CHUNKS = 3
RAG_MIN_CHUNK_LENGTH = 50
RAG_MAX_CHUNK_LENGTH = 500
RAG_SIMILARITY_THRESHOLD = 0.15

# Script execution
SCRIPT_TIMEOUT = 60
SCRIPT_TIMEOUT_SECONDS = 30
SCRIPT_MAX_OUTPUT_LENGTH = 10000

# No API keys here any more: the Google Fact Check integration went with
# TruthTableChecker in Tier 0.1. It had near-zero coverage of academic claims and
# wrote "No API key configured" into 233 user-facing explanation strings on the
# reference run. GOOGLE_FACT_CHECK_API_KEY in an existing .env is now inert.

