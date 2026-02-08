# ASV: Automated Source Validation

## Problem Statement

Statistical metrics often misconstrue data in favor of a specific narrative - even if the statements are not necessarily false. Simple examples include:
- Taking the mean of skewed data: "Energy prices on average are higher than last month" when a single energy price spike outlier exists
- Statistical fallacies: "The average person has less than 2 arms, thus you are very likely to meet amputees"

These problems are prevalent in news and academic media. This project falls under 'source validation', 'source evaluation', and 'citation analysis'.

## Goal

Given a body of text (academic paper, article, etc.), for each claim:
1. **Extract claims** and map them to citations
2. **Classify claims** (quantitative/qualitative, cited/uncited)
3. **Find or download sources** (datasets for quantitative, texts for qualitative)
4. **Validate claims** against sources
5. **Output structured results** with confidence scores

## Architecture: 3-Stage Pipeline

```
┌─────────────────────────────┐
│  Stage 1: Claim Extraction  │
│  (hybrid_citation_scraper)  │
└─────────────┬───────────────┘
              │ ClaimObject[]
              ▼
┌─────────────────────────────┐
│   Stage 2: Orchestration    │
│       (validator)           │
│  - Routes claims by type    │
│  - Manages batch processing │
│  - Calls sourcefinder tools │
└─────────────┬───────────────┘
              │ Uses utilities
              ▼
┌─────────────────────────────┐
│   Stage 3: Utilities        │
│   (sourcefinder_tools)      │
│  - Find datasets/texts      │
│  - Download sources         │
└─────────────────────────────┘
```

### Stage 1: Claim Extraction (`hybrid_citation_scraper/`)

**Purpose:** Extract claims and citations from research papers

**Process:**
1. Load PDF using LangChain PyPDFLoader
2. Extract title and abstract (first ~50 lines)
3. Parse citations using regex + LLM fallback
4. Locate reference section (70% heuristic / 30% fallback)
5. Chunk text (800 tokens, 100-char overlap)
6. Use LLM to extract claims from each chunk
7. Map citations to claims
8. Return sorted claims

**Key Features:**
- Hybrid citation parsing (regex + LLM)
- LLM determines `is_original` field (paper's own contributions)
- Filters out common knowledge claims
- Sorts claims: qual uncited → quant uncited → qual cited → quant cited

**Output:** List of `ClaimObject` with citation mapping

### Stage 2: Orchestration (`validator/`)

**Purpose:** Main orchestrator for claim validation

**Process (in order):**

1. **Qualitative Uncited Claims**
   - Truth Table check (Google Fact Check API)
   - LLM plausibility check
   - If EITHER passes → valid

2. **Quantitative Uncited Claims**
   - Truth Table + LLM check
   - If insufficient → use `DatasetFinder` to find source
   - Mark `originally_uncited=True`, add `found_source`
   - Append to quantitative cited group

3. **Quantitative Cited Claims** (including originally uncited)
   - Batch by `citation_id`
   - Download dataset once per batch
   - Generate Python script to validate claim
   - Execute script, parse JSON output

4. **Qualitative Cited Claims**
   - Batch by `citation_id`
   - Download text source once per batch
   - RAG: TF-IDF retrieval + LLM verification
   - Return confidence + supporting quotes

**Key Features:**
- Batch processing by citation (download once, validate many)
- Failed download → entire batch fails
- Tracks found datasets for reuse
- Separate JSON outputs per claim type

### Stage 3: Utilities (`sourcefinder_tools/`)

**Purpose:** Tools for finding and downloading sources

**Modules:**
- `dataset_finder.py`: Search datasets, manage reuse (LLM decides applicability)
- `text_finder.py`: Search text sources (Scholar, arXiv, etc.)
- `dataset_downloader.py`: Download CSV/JSON/Excel
- `text_downloader.py`: Download PDF/HTML, extract text

**Key Features:**
- Dataset reuse with confidence threshold (0.75)
- Automatic format detection
- Error handling and timeouts

## Data Flow

```
PDF Input
    ↓
[ClaimExtractor] → ClaimObject[]
    ↓
[ClaimValidator]
    ├→ Uncited Qualitative → Truth Table + LLM → ValidationResult[]
    ├→ Uncited Quantitative → Find Sources → Modified ClaimObject[]
    ├→ Cited Quantitative → Batch Download → Python Scripts → ValidationBatch[]
    └→ Cited Qualitative → Batch Download → RAG + LLM → ValidationBatch[]
    ↓
JSON Output Files:
- qualitative_uncited_results.json
- quantitative_uncited_results.json
- quantitative_cited_results.json
- qualitative_cited_results.json
```

## Key Models

### ClaimObject
```python
{
    "claim_id": str,
    "text": str,
    "claim_type": "qualitative" | "quantitative",
    "citation_found": bool,
    "citation_id": Optional[str],
    "citation_text": Optional[str],
    "citation_details": Optional[CitationDetails],
    "is_original": bool,  # Paper's own contribution
    "originally_uncited": bool,  # Source found by validator
    "found_source": Optional[FoundDatasetSource]
}
```

### ValidationResult
```python
{
    "claim_id": str,
    "claim_type": str,
    "originally_uncited": bool,
    "validated": bool,
    "validation_method": str,
    "confidence": float,
    "passed": bool,
    "explanation": str,
    "sources_used": List[str],
    "errors": Optional[str]
}
```

### ValidationBatch
```python
{
    "citation_id": str,
    "citation_text": str,
    "download_successful": bool,
    "source_path": Optional[str],
    "claim_results": List[ValidationResult],
    "batch_notes": str
}
```

## Usage

### Complete Pipeline

```python
from hybrid_citation_scraper import ClaimExtractor
from validator import ClaimValidator

# Stage 1: Extract claims
extractor = ClaimExtractor(api_key="your_openai_key")
claims = extractor.process_pdf("research_paper.pdf")

# Stage 2: Validate claims
validator = ClaimValidator(output_dir="validation_results")
results = validator.process_claims(claims)

# Results saved to:
# - validation_results/qualitative_uncited_results.json
# - validation_results/quantitative_uncited_results.json
# - validation_results/quantitative_cited_results.json
# - validation_results/qualitative_cited_results.json
```

### Access Results

```python
# Qualitative uncited (list of ValidationResult)
qual_uncited = results["qualitative_uncited"]

# Quantitative uncited (list of ValidationResult)
quant_uncited = results["quantitative_uncited"]

# Quantitative cited (list of ValidationBatch)
quant_cited = results["quantitative_cited"]
for batch in quant_cited:
    print(f"Citation: {batch.citation_id}")
    print(f"Downloaded: {batch.download_successful}")
    for claim_result in batch.claim_results:
        print(f"  Claim {claim_result.claim_id}: {'PASSED' if claim_result.passed else 'FAILED'}")

# Qualitative cited (list of ValidationBatch)
qual_cited = results["qualitative_cited"]
```

## Directory Structure

```
ASV/
├── hybrid_citation_scraper/       # Stage 1: Claim extraction
│   ├── claim_extractor.py
│   ├── llm_client.py
│   ├── utils.py
│   ├── config.py
│   └── README.md
│
├── validator/                     # Stage 2: Orchestration
│   ├── claim_validator.py         # Main orchestrator
│   ├── truth_table_checker.py
│   ├── llm_verifier.py
│   ├── quantitative_validator.py
│   ├── qualitative_validator.py
│   ├── config.py
│   └── README.md
│
├── sourcefinder_tools/            # Stage 3: Utilities
│   ├── dataset_finder.py
│   ├── text_finder.py
│   ├── dataset_downloader.py
│   ├── text_downloader.py
│   ├── config.py
│   └── README.md
│
├── models.py                      # Pydantic data models
├── requirements.txt
└── README.md
```

## Dependencies

```txt
openai>=1.0.0
langchain>=0.1.0
pypdf>=3.0.0
pydantic>=2.0.0
python-dotenv>=1.0.0
requests>=2.31.0
scikit-learn>=1.3.0
numpy>=1.24.0
pandas>=2.0.0
PyPDF2>=3.0.0
beautifulsoup4>=4.12.0
lxml>=4.9.0
openpyxl>=3.1.0
```

## Configuration

### Environment Variables

```bash
# .env file
OPENAI_API_KEY=your_openai_key_here
GOOGLE_FACT_CHECK_API_KEY=your_google_key_here  # Optional
```

### Key Settings

**hybrid_citation_scraper/config.py:**
- `CHUNK_SIZE = 800`
- `CHUNK_OVERLAP = 100`
- `REFERENCE_SECTION_THRESHOLD = 0.7`

**validator/config.py:**
- `TRUTH_TABLE_CONFIDENCE_THRESHOLD = 0.7`
- `LLM_CONFIDENCE_THRESHOLD = 0.6`
- `RAG_TOP_K = 3`
- `SCRIPT_TIMEOUT_SECONDS = 30`

**sourcefinder_tools/config.py:**
- `DATASET_REUSE_CONFIDENCE_THRESHOLD = 0.75`
- `DOWNLOAD_TIMEOUT = 30`

## Validation Methods

### Truth Table Check
- Query Google Fact Check API
- Parse ClaimReview schema
- Interpret textual ratings

### LLM Verification
- Assess plausibility using GPT-4o-mini
- Check scientific accuracy, logical consistency
- Return confidence + reasoning

### Python Script Validation (Quantitative)
- Generate script using LLM
- Load dataset, perform calculations
- Output JSON: `{passed, confidence, explanation}`
- 30-second timeout

### RAG Validation (Qualitative)
- Split source into chunks (~500 chars)
- TF-IDF retrieval (top-3)
- LLM verifies claim against chunks
- Return supporting quotes

## Claim Ordering Rationale

1. **Qualitative Uncited**: Fast, no downloads needed
2. **Quantitative Uncited**: Find sources, prepare for batch validation
3. **Quantitative Cited**: Batch process with downloaded datasets
4. **Qualitative Cited**: Batch process with downloaded texts

This order maximizes efficiency by:
- Processing simple cases first
- Batching downloads by citation
- Reusing found datasets across claims

## Error Handling

- **Batch downloads fail**: All claims in batch marked as failed
- **Script timeout**: 30s limit, capture stderr
- **RAG retrieval fails**: Fallback to first K chunks
- **API errors**: Logged, return validation failed

## Future Enhancements

### High Priority
- Real API integrations (Kaggle, Scholar, arXiv)
- Authentication for protected sources
- Retry logic with exponential backoff
- Cache search results

### Medium Priority
- More sophisticated similarity matching for dataset reuse
- Support for more file formats (Parquet, HDF5)
- Progress tracking for large downloads
- Parallel batch processing

### Low Priority
- Web interface for results visualization
- Browser extension for in-browser validation
- Cross-dataset validation
- Trustworthiness scoring for sources

## Contributing

See module-specific READMEs:
- [Claim Extraction](hybrid_citation_scraper/README.md)
- [Validator](validator/README.md)
- [Sourcefinder Tools](sourcefinder_tools/README.md)

## License

[Add license information]
