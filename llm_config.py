"""Global LLM configuration for the ASV workspace."""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables once at workspace level.
load_dotenv(Path(__file__).parent / ".env")

# API Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    print("Warning: GEMINI_API_KEY not found in environment variables")

# Cost tracking for all LLM calls
ENABLE_COST_TRACKING = True

# Model tier overrides
LLM_MODEL_SMALL = os.getenv("LLM_MODEL_SMALL", "gemini-2.5-flash-lite")
LLM_MODEL_MEDIUM = os.getenv("LLM_MODEL_MEDIUM", "gemini-2.5-flash")
LLM_MODEL_STRONG = os.getenv("LLM_MODEL_STRONG", "gemini-2.5-pro")

# Generic fallback defaults
DEFAULT_LLM_MODEL = LLM_MODEL_SMALL
DEFAULT_LLM_TEMPERATURE = 0.2

# Task-to-model routing and budget table.
LLM_TASK_CONFIG = {
    "claim_extraction": {
        "model": LLM_MODEL_SMALL,
        "strength": "small",
        "cost_tier": "low",
        "temperature": 0.1,
        "daily_budget_usd": 1.50,
        "escalate_to": None,
        "escalate_if_confidence_below": None,
    },
    "reference_parsing": {
        "model": LLM_MODEL_SMALL,
        "strength": "small",
        "cost_tier": "low",
        "temperature": 0.1,
        "daily_budget_usd": 0.30,
        "escalate_to": None,
        "escalate_if_confidence_below": None,
    },
    "plausibility_check": {
        "model": LLM_MODEL_SMALL,
        "strength": "small",
        "cost_tier": "low",
        "temperature": 0.2,
        "daily_budget_usd": 0.75,
        "escalate_to": "source_grounded_verification",
        "escalate_if_confidence_below": 0.70,
    },
    "source_grounded_verification": {
        "model": LLM_MODEL_MEDIUM,
        "strength": "medium",
        "cost_tier": "medium",
        "temperature": 0.15,
        "daily_budget_usd": 1.50,
        "escalate_to": "quant_script_generation",
        "escalate_if_confidence_below": 0.60,
    },
    "quant_script_generation": {
        "model": LLM_MODEL_STRONG,
        "strength": "strong",
        "cost_tier": "high",
        "temperature": 0.1,
        "daily_budget_usd": 2.00,
        "escalate_to": None,
        "escalate_if_confidence_below": None,
    },
    "dataset_reuse_decision": {
        "model": LLM_MODEL_SMALL,
        "strength": "small",
        "cost_tier": "low",
        "temperature": 0.2,
        "daily_budget_usd": 0.25,
        "escalate_to": None,
        "escalate_if_confidence_below": None,
    },
    "generic": {
        "model": DEFAULT_LLM_MODEL,
        "strength": "small",
        "cost_tier": "low",
        "temperature": DEFAULT_LLM_TEMPERATURE,
        "daily_budget_usd": 0.50,
        "escalate_to": None,
        "escalate_if_confidence_below": None,
    },
}
