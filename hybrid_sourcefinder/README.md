# Hybrid Source Finder

**Step 2: Claim Type Treatment** - Source finding and downloading pipeline for claim validation.

Processes claims from Step 1 (hybrid_citation_scraper) and maps them to appropriate data sources:
- Downloads datasets for quantitative claims
- Downloads text sources for qualitative claims
- Searches for missing datasets
- Queries fact-checking databases for unverified claims

## Features

- **Source Finder**: Downloads datasets (CSV, JSON, Excel) from citation URLs and DOIs
- **Dataset Searcher**: LLM-powered search across data repositories (data.gov, Kaggle, etc.)
- **Text Downloader**: Downloads PDFs, web pages, and text sources for qualitative claims
- **Truth Table Checker**: Queries Google Fact Check API and other fact-checking databases
- **Claim Treatment Agent**: Main orchestrator that routes claims to appropriate handlers

## Architecture

```
ClaimTreatmentAgent (Main Orchestrator)
├── Quantitative + Citation → SourceFinder → Download dataset
├── Quantitative - Citation → DatasetSearcher → Find & download
├── Qualitative + Citation → TextDownloader → Download text
└── Qualitative - Citation (Subjective) → TruthTableChecker → Verify
```

## Installation

```bash
# Install dependencies
pip install -r requirements.txt

# Required: OpenAI API key (for LLM features)
echo "OPENAI_API_KEY=your-key-here" >> ../geminikey.env

# Optional: Google Fact Check API (for truth table queries)
echo "GOOGLE_FACT_CHECK_KEY=your-key-here" >> ../geminikey.env

# Optional: Kaggle API (for dataset search)
echo "KAGGLE_USERNAME=your-username" >> ../geminikey.env
echo "KAGGLE_KEY=your-key" >> ../geminikey.env
```

## Usage

### Command Line

Process claims from Step 1 output:

```bash
# Process claims from Step 1
python -m hybrid_sourcefinder.claim_treatment_agent path/to/step1_claims.json --output-dir ./treated_claims
```

### Python API

```python
from hybrid_sourcefinder import ClaimTreatmentAgent
from hybrid_citation_scraper.models import ClaimObject

# Initialize the agent
agent = ClaimTreatmentAgent(output_dir="./treated_claims")

# Load claims from Step 1
claims = agent.load_claims_from_step1("paper_claims.json")

# Process claims through treatment pipeline
treated_claims = agent.process_claims(claims)

# Save results
output_path = agent.save_results()

# Access individual treated claims
for claim in treated_claims:
    print(f"Claim: {claim.text}")
    print(f"Mapped: {claim.citation_mapped}")
    print(f"Source: {claim.citation_source}")
    print(f"Notes: {claim.treatment_notes}")
    print()
```

### Individual Components

#### Source Finder (Dataset Download)

```python
from hybrid_sourcefinder import SourceFinder

finder = SourceFinder(output_dir="./data")

# Download from direct URL
result = finder.download_dataset("https://example.com/data.csv", claim_id="claim-001")

# Download from citation details
citation = {
    'url': 'https://example.com/data.csv',
    'doi': '10.1234/example',
    'title': 'Example Dataset'
}
result = finder.download_from_citation(citation, claim_id="claim-001")

print(f"Downloaded: {result['downloaded']}")
print(f"Format: {result['data_format']}")
print(f"Path: {result['local_path']}")
```

#### Dataset Searcher (Find Datasets)

```python
from hybrid_sourcefinder import DatasetSearcher
from hybrid_citation_scraper.llm_client import LLMClient

searcher = DatasetSearcher(llm_client=LLMClient())

# Search for datasets
claim_text = "Energy prices increased by 15% last month"
datasets = searcher.search_datasets(claim_text, top_k=5)

for dataset in datasets:
    print(f"Title: {dataset['title']}")
    print(f"URL: {dataset['url']}")
    print(f"Source: {dataset['source']}")
    print(f"Relevance: {dataset['relevance_score']}")
    print()

# Get best match only
best = searcher.get_best_match(claim_text)
```

#### Text Downloader (Qualitative Sources)

```python
from hybrid_sourcefinder import TextDownloader

downloader = TextDownloader(output_dir="./sources")

# Download PDF, HTML, or text
result = downloader.download_text_source(
    "https://example.com/paper.pdf",
    claim_id="claim-002"
)

print(f"Downloaded: {result['downloaded']}")
print(f"Format: {result['data_format']}")
print(f"Text length: {len(result['text_content'])}")

# Extract relevant snippet
snippet = downloader.get_text_snippet(
    result['text_content'],
    "claim text to search for"
)
```

#### Truth Table Checker (Fact Verification)

```python
from hybrid_sourcefinder import TruthTableChecker
from hybrid_citation_scraper.llm_client import LLMClient

checker = TruthTableChecker(llm_client=LLMClient())

# Check a claim
claim_text = "The Earth is flat"
result = checker.check_claim(claim_text)

print(f"Found: {result['found']}")
print(f"Rating: {result['rating']}")  # 'true', 'false', 'mixed', 'unverified'
print(f"Confidence: {result['confidence']}")
print(f"Method: {result['method']}")  # 'truth_table', 'llm_search', 'not_found'
print(f"Sources: {len(result['sources'])}")
print(f"Explanation: {result['explanation']}")
```

## Claim Type Treatment Logic

### Quantitative + Citation Found
1. Extract URL/DOI from citation details
2. Download dataset using SourceFinder
3. Save to local path for Step 3 validation

### Quantitative + No Citation
1. Generate search queries using LLM
2. Search data repositories (data.gov, Kaggle)
3. Rank results by relevance
4. Download best match if confidence > threshold

### Qualitative + Citation Found (Objective)
1. Extract URL/DOI from citation
2. Download raw text (PDF, HTML)
3. Extract and save text content for Step 3 validation

### Qualitative + No Citation (Subjective)
1. Query Google Fact Check API
2. Check ClaimReview structured data
3. Fallback to LLM fact-check with sources
4. Return verification result if confidence > threshold

## Output Format

Each claim is converted to `ClaimObjectAfterTreatment`:

```python
{
  "claim_id": "unique-identifier",
  "text": "The claim text",
  "claim_type": "quantitative",  # or "qualitative"
  "citation_mapped": True,
  "citation_source": {
    "downloaded": True,
    "data_format": "csv",
    "platform": "pandas",
    "source_url": "https://example.com/data.csv",
    "local_path": "./treated_claims/datasets/claim_unique-identifier_dataset.csv"
  },
  "treatment_notes": "Citation found and dataset downloaded for validation."
}
```

## Configuration

Edit [config.py](config.py) to customize:

- Output directories
- API endpoints
- Search parameters
- Confidence thresholds
- Timeout settings

## Data Sources

### Supported Repositories
- **data.gov**: US government open data
- **Kaggle**: Community datasets (requires API key)
- **Google Dataset Search**: (placeholder, web scraping needed)
- **DOI resolution**: Academic datasets via DOI

### Fact-Checking Sources
- **Google Fact Check Tools API**: Verified fact-checks
- **ClaimReview Schema**: Structured fact-check data
- **LLM Search**: Fallback with source citations

## Integration with Step 1

This module takes output from `hybrid_citation_scraper`:

```python
# Step 1: Extract claims
from hybrid_citation_scraper import HybridClaimExtractor

extractor = HybridClaimExtractor()
claims, citations = extractor.process_pdf("paper.pdf")
extractor.save_results("paper_claims.json")

# Step 2: Treat claims
from hybrid_sourcefinder import ClaimTreatmentAgent

agent = ClaimTreatmentAgent()
claims_from_step1 = agent.load_claims_from_step1("paper_claims.json")
treated_claims = agent.process_claims(claims_from_step1)
agent.save_results("treated_claims.json")
```

## Error Handling

The module handles various failure modes gracefully:

- **Network errors**: Logged with retry suggestions
- **Missing API keys**: Falls back to deterministic methods
- **Download failures**: Captured in `treatment_notes`
- **No sources found**: Marked as unmapped for manual review

## Limitations

1. **Dataset Search**: Limited to public repositories with APIs
2. **Paywall Content**: Cannot download behind paywalls
3. **Complex DOIs**: Some DOIs may not resolve to downloadable data
4. **Fact-Checking Coverage**: Not all claims have fact-checks available
5. **API Rate Limits**: Subject to API provider limits

## Next Steps

Output from this module feeds into:

**Step 3: Claim Validation** - Validates claims against downloaded sources
- Run Python code to verify quantitative claims
- Use semantic search/RAG for qualitative claims
- Generate judgment objects

## Dependencies

- `requests`: HTTP client for downloads
- `pandas`: Dataset handling and validation
- `PyPDF2`: PDF text extraction
- `beautifulsoup4`: HTML parsing
- `kaggle`: Kaggle API client (optional)
- `openpyxl`: Excel file support

Plus dependencies from `hybrid_citation_scraper`:
- `openai`: LLM client
- `pydantic`: Data models

## Contributing

When adding new data sources:
1. Implement search method in `dataset_searcher.py`
2. Add API configuration to `config.py`
3. Update documentation

## License

Part of the ASV (Automated Source Valuation) project.
