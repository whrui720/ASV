# Sourcefinder Tools

Utility tools for finding and downloading sources (datasets and text documents). These tools are used by the `validator` module to locate evidence for uncited claims. NOTE: This folder does not contain any tools for validation (e.g. truth table lookup, basic LLM checks, etc.); those validation tools (and logic) can all be found in the validator folder.

## Purpose

This module provides **utilities** (not orchestration) for:
1. Finding relevant datasets for quantitative claims
2. Finding relevant text sources for quantitative, or qualitative claims
3. Downloading datasets in various formats
4. Downloading and extracting text from PDFs and HTML

## Modules

### dataset_finder.py
Used when a quantitative claim is detected as verifiable by a dataset, but does not have an actual dataset citation accompanying. 
Thus, this class searches for appropriate datasets, and manages dataset reuse (previously found datasets will be prioritized/reused so that several quantitative claims without citations may be batched together on a single found dataset).

**Key Features:**
- Search dataset repositories (Kaggle, Google Dataset Search, etc.)
- Check if existing datasets can be reused for similar claims
- LLM decides dataset applicability with confidence threshold
- Track `reused_count` for dataset reuse
- Return `FoundDatasetSource` objects

**API:**
```python
from sourcefinder_tools import DatasetFinder

finder = DatasetFinder(llm_client=llm_client)

# Find dataset for a claim
found_source = finder.find_dataset(
    claim_text="The unemployment rate increased by 5%",
    claim_id="paper123_claim_5"
)

# Returns FoundDatasetSource or None
# {
#     "source_type": "kaggle_dataset",
#     "source_url": "https://kaggle.com/...",
#     "source_id": "unemployment_stats_2023",
#     "confidence": 0.85,
#     "reused_count": 0,
#     "original_claim_id": "paper123_claim_5"
# }
```

**Dataset Reuse Logic:**
- DatasetFinder maintains its own internal list of found datasets
- Before searching, checks if any previously found dataset can answer the new claim
- LLM evaluates: "Can this dataset answer this claim?"
- Returns JSON: `{applicable: bool, confidence: 0.0-1.0, reasoning: str}`
- If confidence > 0.75 → reuse dataset, increment `reused_count`
- Otherwise → search for new dataset and add to internal list
- All dataset state is managed within DatasetFinder, not by the caller

### text_finder.py
Used when a quantitative or qualitative claim is detected as verifiable by a text source, but does not have an actual text citation accompanying. Does NOT prioritize reuse as dataset_finder does. Searches for relevant text sources:

**API:**
```python
from sourcefinder_tools import TextFinder

finder = TextFinder(llm_client=llm_client)

# Find text source for a claim
found_source = finder.find_text_source(
    claim_text="Neural networks improve accuracy",
    claim_id="paper123_claim_7"
)

# Returns FoundDatasetSource or None
# {
#     "source_type": "arxiv_paper",
#     "source_url": "https://arxiv.org/pdf/2301.12345",
#     "source_id": "arxiv_2301_12345",
#     "confidence": 0.90,
#     "reused_count": 0,
#     "original_claim_id": "paper123_claim_7"
# }
```

**Note:** Currently contains placeholder implementation. Real implementation should use:
- Google Scholar API
- arXiv API
- Semantic Scholar API
- PubMed API

### dataset_downloader.py
Download datasets in various formats:

**Supported Formats:**
- CSV
- JSON
- Excel (.xlsx, .xls)

**API:**
```python
from sourcefinder_tools import DatasetDownloader

downloader = DatasetDownloader()

# Download dataset
result = downloader.download(
    url="https://example.com/data.csv",
    citation_id="paper123_ref_5"
)

# Returns dict:
# {
#     "downloaded": true,
#     "path": "/downloads/datasets/paper123_ref_5.csv",
#     "format": "csv",
#     "error": null
# }

# Delete dataset
result = downloader.delete_dataset(
    filename="citation_paper123_ref_5_dataset.csv"
)

# Returns dict:
# {
#     "deleted": true,
#     "path": "/datasets/citation_paper123_ref_5_dataset.csv",
#     "error": null
# }
```

**Features:**
- Automatic format detection from URL/content-type
- Saves to `downloads/datasets/{citation_id}.{ext}`
- Handles HTTP errors and timeouts
- Returns error messages on failure

### text_downloader.py
Download and extract text from PDFs and HTML:

**API:**
```python
from sourcefinder_tools import TextDownloader

downloader = TextDownloader()

# Download text source
result = downloader.download(
    url="https://arxiv.org/pdf/2301.12345.pdf",
    citation_id="paper123_ref_8"
)

# Returns dict:
# {
#     "downloaded": true,
#     "path": "/downloads/texts/paper123_ref_8.pdf",
#     "format": "pdf",
#     "text_content": "Full extracted text...",
#     "error": null
# }

# Delete text file
result = downloader.delete_text(
    filename="citation_paper123_ref_8_text.pdf"
)

# Returns dict:
# {
#     "deleted": true,
#     "path": "/text_sources/citation_paper123_ref_8_text.pdf",
#     "error": null
# }
```

**Features:**
- PDF text extraction using PyPDF2
- HTML text extraction using BeautifulSoup4
- Automatic format detection
- Saves original file to `downloads/texts/{citation_id}.{ext}`
- Returns extracted text in `text_content` field

## Configuration

Settings in `config.py`:

```python
# Download directories
DOWNLOADS_DIR = "downloads"
DATASET_DOWNLOAD_DIR = "downloads/datasets"
TEXT_DOWNLOAD_DIR = "downloads/texts"

# API endpoints (placeholders)
KAGGLE_API_ENDPOINT = "https://www.kaggle.com/api/v1"
GOOGLE_DATASET_SEARCH_API = "https://datasetsearch.research.google.com"
ARXIV_API_ENDPOINT = "http://export.arxiv.org/api"
SEMANTIC_SCHOLAR_API = "https://api.semanticscholar.org"

# Thresholds
DATASET_REUSE_CONFIDENCE_THRESHOLD = 0.75
SOURCE_SEARCH_TIMEOUT = 10  # seconds
DOWNLOAD_TIMEOUT = 30  # seconds
```

## Data Models

### FoundDatasetSource
```python
{
    "source_type": str,  # "kaggle_dataset", "arxiv_paper", etc.
    "source_url": str,  # Direct download URL
    "source_id": str,  # Unique identifier
    "confidence": float,  # 0.0-1.0
    "reused_count": int,  # Number of times reused
    "original_claim_id": str  # First claim that found this source
}
```

## Usage in Validator

The validator uses these tools internally:

```python
# In validator/claim_validator.py

# Find dataset for uncited quantitative claim
# DatasetFinder manages dataset reuse internally
found_source = self.dataset_finder.find_dataset(
    claim.text,
    claim.claim_id
)

# Download dataset for cited quantitative claim
download_result = self.dataset_downloader.download(
    claim.citation_details.url,
    claim.citation_id
)

# Download text for cited qualitative claim
download_result = self.text_downloader.download(
    claim.citation_details.url,
    claim.citation_id
)
```

## Dataset Reuse Example

```python
# Claim 1: "Unemployment rate is 5%"
# DatasetFinder searches and finds dataset: unemployment_stats_2023.csv
# Stores internally in dataset_finder.found_datasets:
# [
#     FoundDatasetSource(
#         source_type="kaggle_dataset",
#         source_url="https://kaggle.com/unemployment",
#         source_id="unemployment_stats_2023",
#         confidence=0.85,
#         reused_count=0,
#         original_claim_id="paper123_claim_5"
#     )
# ]

# Claim 2: "Employment numbers dropped"
# DatasetFinder checks its internal list first (automatically)
# LLM determines unemployment dataset is applicable
# Reuses dataset, increments reused_count=1
# No manual tracking by validator required
```

## Error Handling

### Dataset Finder
- Search timeout → return None
- No results found → return None
- API errors → logged, return None

### Text Finder
- Search timeout → return None
- No results found → return None
- API errors → logged, return None

### Downloaders
- HTTP errors → return `{downloaded: false, error: "HTTP 404"}`
- Timeout → return `{downloaded: false, error: "Timeout"}`
- Invalid format → return `{downloaded: false, error: "Unsupported format"}`
- Extraction failed → file saved but text_content is empty

## Dependencies

```
requests
pandas
PyPDF2
beautifulsoup4
lxml
openpyxl  # For Excel files
```

## Future Enhancements

### Dataset Finder
- Integrate real APIs (Kaggle, Google Dataset Search)
- Add authentication for API keys
- Improve search relevance with semantic matching
- Cache search results

### Text Finder
- Integrate Scholar/arXiv/Semantic Scholar APIs
- Add DOI resolution
- Prioritize open-access sources
- Handle paywalls gracefully

### Downloaders
- Add retry logic with exponential backoff
- Support more formats (Parquet, HDF5, etc.)
- Validate downloaded content
- Add progress tracking for large files
- Handle authentication/tokens for protected sources

## Testing

```python
# Test dataset finder
finder = DatasetFinder(llm_client=llm_client)
result = finder.find_dataset("COVID-19 cases increased", "test_1")
assert result is not None
assert result.source_url
assert result.confidence > 0.5

# Test downloader
downloader = DatasetDownloader()
result = downloader.download("https://example.com/data.csv", "test_citation")
assert result['downloaded'] == True
assert os.path.exists(result['path'])
```
