"""Configuration for the agentic citation scraper"""


# Citation Detection Settings
CITATION_STYLES = {
    'numeric': r'^\d+\.?\s+\w+',       # "1. Author..." or "1 Author..." (period optional)
    'bracket_numeric': r'^\[\d+\]\s+\w+',  # "[1] Author..."
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

# Output directory for extracted claims (relative to project root)
CLAIM_EXTRACTION_OUTPUT_DIR = "./hybrid_citation_scraper/test_outputs"
