"""Configuration for the agentic citation scraper"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv(Path(__file__).parent.parent / "geminikey.env")

# API Configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    print("Warning: OPENAI_API_KEY not found in environment variables")

# Model Settings
CLAIM_EXTRACTION_MODEL = "gpt-4o-mini"  # Cost: $0.150/M input tokens
CLAIM_EXTRACTION_TEMPERATURE = 0.1  # Low temperature for structured output

# Citation Detection Settings
CITATION_STYLES = {
    'numeric': r'^\d+\.\s+\w+',  # "1. Author..."
    'apa': r'^\w+,\s+\w\.\s+\(\d{4}\)',  # "Smith, J. (2020)..."
    'mla': r'^\w+,\s+\w+\.\s+["\']',  # "Smith, John. "Title..."
    'chicago': r'^\w+,\s+\w+,\s+and\s+\w+',  # "Smith, John, and..."
    'vancouver': r'^\d+\.\s+\w+\s+\w+\.',  # "1. Smith J."
}

# Reference Section Keywords
REFERENCE_KEYWORDS = [
    "References",
    "REFERENCES", 
    "Bibliography",
    "BIBLIOGRAPHY",
    "Works Cited",
    "WORKS CITED",
    "Literature Cited"
]

# Chunking Settings
CHUNK_SIZE = 800  # tokens per chunk
CHUNK_OVERLAP = 100  # overlap between chunks

# Cost Tracking
ENABLE_COST_TRACKING = True
