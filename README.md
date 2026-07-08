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
│   (sourcefinder)            │
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

### Stage 2: Orchestration (`orchestrator/`)

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
   - Batch by `citation_id`, then split by source shape:
     - **Dataset-backed** (`found_source` populated by `DatasetFinder`): download tabular data once, generate Python script to validate claim, execute script and parse JSON output
     - **Paper-backed** (`found_source is None`, i.e. the citation is a paper): download paper text once via `TextDownloader.download_with_resolution`, verify each claim via RAG (TF-IDF + LLM) against the paper — same path as qualitative-cited. `claim_type` stays `"quantitative"`.
   - Both sub-paths emit `ValidationBatch` into the same output list; downstream consumers don't need to distinguish them.

4. **Qualitative Cited Claims**
   - Batch by `citation_id`
   - Download text source once per batch via `TextDownloader.download_with_resolution` (iterates OA candidates, rejects <200-char extractions, cleans HTML article body)
   - RAG: TF-IDF retrieval + LLM verification
   - Return confidence + supporting quotes

**Key Features:**
- Batch processing by citation (download once, validate many)
- Failed download → entire batch fails
- Tracks found datasets for reuse
- Separate JSON outputs per claim type

### Stage 3: Utilities (`sourcefinder/`)

**Purpose:** Tools for finding and downloading sources

**Modules:**
- `dataset_finder.py`: Search datasets, manage reuse (LLM decides applicability)
- `text_finder.py`: Search text sources (Scholar, arXiv, etc.)
- `academic_paper_finder.py`: Resolve citations to open-access URLs via Unpaywall → Semantic Scholar → CrossRef → title-search cascade. Never returns raw DOI landing URLs (those content-negotiate to metadata and rarely serve content).
- `dataset_downloader.py`: Download CSV/JSON/Excel with content sniffing. Single session GET, format detected from magic bytes + Content-Type + URL; non-tabular payloads (PDF/HTML/JSON metadata) are rejected with an explicit `"URL is not tabular data"` error so the caller can iterate.
- `text_downloader.py`: Download PDF/HTML with a hardened extraction chain — magic-byte format detection, PDF fallback `pymupdf → pdfminer.six → pypdf`, HTML article-body extraction (strips nav chrome + prefers `<article>/<main>/[role="main"]`), and a 200-char usable-text gate that treats empty extractions as download failures.

**Key Features:**
- Dataset reuse with confidence threshold (0.75)
- Content-sniffing format detection (magic bytes dominate URL and Content-Type)
- Iterative candidate URL resolution with per-attempt manifest logging
- 200-char extracted-text gate prevents empty-source silent fallbacks
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
JSON Output Files (under runs/{pdf_stem}__{timestamp}/validation_results/):
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
    "originally_uncited": bool,  # Source found by orchestrator
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

### Canonical entry point (recommended)

```bash
python scripts/run_pipeline.py pdfs/research_paper.pdf
```

This creates a fresh run folder at `runs/{pdf_stem}__{YYYYMMDD_HHMMSS}/` and writes every artifact under it (claims JSON, source discovery records, generated scripts, downloads, validation results, run summary, log).

### Programmatic usage

```python
from hybrid_citation_scraper.claim_extractor import HybridClaimExtractor
from orchestrator import ClaimOrchestrator
from run_paths import RunPaths

# Set up the run folder
run_paths = RunPaths.for_pdf("pdfs/research_paper.pdf")

# Stage 1: Extract claims
extractor = HybridClaimExtractor()
claims, citations = extractor.process_pdf("pdfs/research_paper.pdf")
extractor.save_results(pdf_path="pdfs/research_paper.pdf", run_paths=run_paths)

# Stage 2: Validate claims
orchestrator = ClaimOrchestrator(run_paths=run_paths)
results = orchestrator.process_claims(claims, citations)

# Results saved under run_paths.validation_results, run_paths.run_summary_json(), etc.
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
├── docs/                          # Project documentation
│   ├── README.md
│   └── testing/
│       ├── README.md
│       ├── INSTALLATION_AND_USAGE.md
│       ├── TESTING_GUIDE.md
│       └── TEST_SUITE_SUMMARY.md
│
├── scripts/                       # Entry points + utility scripts
│   ├── README.md
│   ├── run_pipeline.py            # ← canonical end-to-end entry point
│   ├── run_orchestrator.py        # ← rerun orchestration on a claims JSON
│   ├── run_tests.py
│   └── run_tests.ps1
│
├── pdfs/                          # Input PDFs (gitignored)
│
├── runs/                          # Per-PDF output folders (gitignored)
│   └── {pdf_stem}__{YYYYMMDD_HHMMSS}/
│       ├── citations/             # {pdf_stem}_claims.json
│       ├── sourcefinder/          # found_datasets.json + found_text_sources.json
│       ├── generated_scripts/     # validate_{claim_id}.py
│       ├── datasets/              # citation_{id}_dataset.{csv|json|xlsx}
│       ├── text_sources/          # citation_{id}_text.{pdf|html|txt}
│       ├── validation_results/    # 4 result JSONs
│       ├── final_output/          # run_summary.json
│       └── logs/                  # orchestration.log
│
├── hybrid_citation_scraper/       # Stage 1: Claim extraction
│   ├── claim_extractor.py
│   ├── llm_client.py
│   ├── utils.py
│   ├── config.py
│   └── README.md
│
├── orchestrator/                  # Stage 2: Orchestration
│   ├── claim_orchestrator.py      # Main orchestrator
│   ├── process_quantitative.py
│   ├── process_qualitative.py
│   └── __init__.py
│
├── validator/                     # Validation tools
│   ├── truth_table_checker.py
│   ├── llm_verifier.py
│   ├── python_script_validator.py
│   ├── config.py
│   ├── __init__.py
│   └── README.md
│
├── sourcefinder/                  # Stage 3: Utilities
│   ├── dataset_finder.py
│   ├── text_finder.py
│   ├── academic_paper_finder.py   # OA-URL resolution (Unpaywall / S2 / CrossRef)
│   ├── dataset_downloader.py      # content-sniffing tabular downloader
│   ├── text_downloader.py         # hardened PDF/HTML downloader + extractor
│   ├── source_manifest.py         # per-batch resolution cascade logging
│   ├── config.py
│   └── README.md
│
├── run_paths.py                   # RunPaths dataclass — owns per-PDF layout
├── models.py                      # Pydantic data models
├── llm_config.py                  # Gemini API + task routing table
├── requirements.txt
└── README.md
```

## Dependencies

Authoritative list is `requirements.txt`. Highlights:

```txt
# LLM
google-genai>=1.0.0          # Gemini API (replaces legacy google-generativeai)
google-cloud-bigquery==3.30.0

# NLP / models
spacy==3.8.4
scikit-learn>=1.3.0
scipy==1.15.3
numpy>=1.24.0
pandas==2.3.3

# PDF extraction (fallback chain: pymupdf → pdfminer.six → pypdf)
PyMuPDF==1.25.1
pdfminer.six
pypdf>=3.0.0
PyPDF2>=3.0.0                # legacy, retained for callers that import it

# HTML & content parsing
beautifulsoup4>=4.12.0
lxml>=4.9.0
openpyxl>=3.1.0              # xlsx support in DatasetDownloader

# Pipeline glue
langchain>=0.1.0
pydantic>=2.0.0
python-dotenv>=1.0.0
requests>=2.31.0

# Optional / fallback source finding
kaggle==1.6.17
rapidfuzz==3.11.0
playwright>=1.40.0           # browser fallback for paywalled searches
```

## Configuration

### Environment Variables

```bash
# .env file
GEMINI_API_KEY=your_gemini_key_here              # Required
GOOGLE_FACT_CHECK_API_KEY=your_google_key_here   # Optional, truth table check
KAGGLE_USERNAME=...                              # Optional, dataset search
KAGGLE_KEY=...
UNPAYWALL_EMAIL=...                              # Optional, open-access PDF lookup
SEMANTIC_SCHOLAR_API_KEY=...                     # Optional

# Optional model tier overrides (task routing table uses these)
LLM_MODEL_SMALL=gemini-2.5-flash-lite
LLM_MODEL_MEDIUM=gemini-2.5-flash
LLM_MODEL_STRONG=gemini-2.5-pro
```

### Key Settings

**hybrid_citation_scraper/config.py:**
- `CHUNK_SIZE = 800`
- `CHUNK_OVERLAP = 100`

**validator/config.py:**
- `TRUTH_TABLE_CONFIDENCE_THRESHOLD = 0.8`
- `LLM_VERIFIER_CONFIDENCE_THRESHOLD = 0.8`
- `DATASET_REUSE_CONFIDENCE = 0.75`
- `RAG_TOP_K = 3`, `RAG_TOP_K_CHUNKS = 3`
- `RAG_MIN_CHUNK_LENGTH = 50`, `RAG_MAX_CHUNK_LENGTH = 500`
- `RAG_SIMILARITY_THRESHOLD = 0.15` — lowered from `0.3` so borderline retrieval hits reach the LLM instead of being silently dropped. Top-K (3) still caps context size.
- `SCRIPT_TIMEOUT_SECONDS = 30`

**sourcefinder/config.py:**
- `DATASET_REUSE_THRESHOLD = 0.75`
- `DOWNLOAD_TIMEOUT = 60`
- `MAX_FILE_SIZE_MB = 500`
- `INSTITUTIONAL_COOKIES` (env, JSON) — optional per-domain cookies for paywalled sources
- `KNOWN_PAYWALL_DOMAINS` — canonical list of domains treated as paywalls when routing candidates
- Open-access API endpoints: `UNPAYWALL_API`, `SEMANTIC_SCHOLAR_API`, `CROSSREF_API`

**sourcefinder/text_downloader.py:**
- `_MIN_USABLE_TEXT_CHARS = 200` — minimum non-whitespace extracted chars required to consider a download successful. Below this, the file is deleted and `download_with_resolution` iterates to the next candidate.

### LLM Task Routing Table

Configured in `llm_config.py` as `LLM_TASK_CONFIG`:

| Task Key | Primary Use Case | Strength | Cost Tier | Default Model | Temperature |
| --- | --- | --- | --- | --- | --- |
| `claim_extraction` | Chunk-level claim extraction | small | low | `LLM_MODEL_SMALL` | 0.1 |
| `reference_parsing` | Citation parsing fallback | small | low | `LLM_MODEL_SMALL` | 0.1 |
| `plausibility_check` | Uncited qualitative plausibility | small | low | `LLM_MODEL_SMALL` | 0.2 |
| `source_grounded_verification` | RAG-based claim/source verification | medium | medium | `LLM_MODEL_MEDIUM` | 0.15 |
| `quant_script_generation` | Python script generation for quantitative checks | strong | high | `LLM_MODEL_STRONG` | 0.1 |
| `dataset_reuse_decision` | Decide whether to reuse found dataset | small | low | `LLM_MODEL_SMALL` | 0.2 |
| `generic` | Backward-compatible default path | small | low | `DEFAULT_LLM_MODEL` | `DEFAULT_LLM_TEMPERATURE` |

Each task entry also includes optional budget and escalation fields:
- `daily_budget_usd`
- `escalate_to`
- `escalate_if_confidence_below`

## Validation Methods

### Truth Table Check
- Query Google Fact Check API
- Parse ClaimReview schema
- Interpret textual ratings

### LLM Verification
- Assess plausibility using the configured Gemini tier
- Check scientific accuracy, logical consistency
- Return confidence + reasoning

### Python Script Validation (Quantitative, dataset-backed only)
- Generate script using LLM
- Load dataset, perform calculations
- Output JSON: `{passed, confidence, explanation}`
- 30-second timeout
- Runs only for cited-quant claims whose `found_source` points at real tabular data (data.gov / Kaggle / Zenodo etc.). Paper-backed cited-quant claims fall through to RAG below.

### RAG Validation (Qualitative + paper-backed Quantitative)
- Split source into chunks (~500 chars, sentence-boundary aware)
- TF-IDF retrieval (top-3, similarity ≥ `RAG_SIMILARITY_THRESHOLD = 0.15`)
- LLM verifies claim against chunks
- Return `passed`, `confidence`, `explanation`, `supporting_quotes`
- Same code path is invoked from `_process_cited_qualitative` and `_process_paper_backed_quant`

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

- **Batch downloads fail**: All claims in batch marked as failed. The batch's `ValidationBatch` has `download_successful=False`, and every `claim_result.errors` includes the underlying error string.
- **Non-tabular URL served to `DatasetDownloader`**: rejected with `"URL is not tabular data (detected: ...)"`. Caller iterates to next candidate rather than saving PDF/HTML bytes as a dataset.
- **PDF extraction fails on all three parsers**: returns empty text → 200-char gate fails → download treated as failure → cascade iterates.
- **HTML login-wall responses**: article-body extractor finds no `<article>`/`<main>` container. If the body text is <200 usable chars, the response is treated as a failure (this is the intended honest-failure path).
- **Script timeout**: 30s limit, capture stderr
- **RAG retrieval fails**: Fallback to first K chunks (only on exception; low-similarity results are simply an empty relevant-chunks list, which fails the batch honestly)
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
- [Sourcefinder](sourcefinder/README.md)

## License

[Add license information]
