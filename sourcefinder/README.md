# Sourcefinder Tools

Utility tools for finding and downloading sources (datasets and text documents). These tools are used by the `orchestrator` module to locate evidence for uncited claims. NOTE: This folder does not contain any tools for validation (e.g. truth table lookup, basic LLM checks, etc.); validation tools are in the `validator` folder and orchestration logic is in the `orchestrator` folder.

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
from sourcefinder import DatasetFinder

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
from sourcefinder import TextFinder

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
Download datasets in various formats, with strict content sniffing so non-tabular payloads never masquerade as datasets:

**Supported Formats:**
- CSV
- JSON
- Excel (.xlsx via OOXML zip signature `PK\x03\x04`, .xls via legacy OLE compound signature `\xd0\xcf\x11\xe0`)

**Rejects (returns `downloaded=False` with a specific error, so caller can iterate):**
- PDF (`%PDF-` magic bytes or `application/pdf` Content-Type)
- HTML (`<!doctype html`/`<html` prefix or `text/html` Content-Type) — publishers frequently serve HTML login walls at `.pdf` URLs
- Unknown / unparseable binary payloads

**Single-fetch design:** one `session.get` fills a `BytesIO` buffer, then `pd.read_csv` / `pd.read_excel` / `json.loads` parse from that buffer. There is no second HTTP fetch (which would risk seeing different bytes than the session headers/cookies delivered).

**Accept header** deliberately omits `application/json`. DOI URLs otherwise content-negotiate to CrossRef bibliographic metadata (title/authors/journal), which is not a dataset and would poison the script validator downstream.

**API:**
```python
from sourcefinder import DatasetDownloader
from run_paths import RunPaths

run_paths = RunPaths.for_pdf("pdfs/paper.pdf")
downloader = DatasetDownloader(run_paths=run_paths)

# Download dataset — succeeds only for tabular formats
result = downloader.download(
    url="https://example.com/data.csv",
    citation_id="paper123_ref_5"
)
# {"downloaded": true, "path": ".../citation_paper123_ref_5_dataset.csv",
#  "format": "csv", "error": None}

# Non-tabular URL — rejected cleanly
result = downloader.download(
    url="https://europepmc.org/articles/pmc319914?pdf=render",
    citation_id="paper123_ref_9"
)
# {"downloaded": false, "path": None, "format": None,
#  "error": "URL is not tabular data (detected: application/pdf)"}

# Delete dataset
result = downloader.delete_dataset(
    filename="citation_paper123_ref_5_dataset.csv"
)
# {"deleted": true, "path": ".../citation_paper123_ref_5_dataset.csv", "error": None}
```

**Features:**
- Magic-byte format detection (PDF, ZIP/OOXML, OLE, HTML) beats URL and Content-Type hints
- URL/Content-Type fallback for CSV/JSON/xlsx/xls
- Content-based JSON/CSV sniffing for unhinted text payloads
- Saves to `run_paths.datasets / citation_{citation_id}_dataset.{ext}` (per-PDF run folder)
- Handles HTTP errors and timeouts; returns error messages on failure

### text_downloader.py
Download and extract text from PDFs and HTML, with a hardened extraction chain and honest failure handling.

**Format detection (`_detect_format`) — magic bytes dominate:**
1. `%PDF-` prefix → `pdf`
2. `<!doctype html` / `<html` prefix → `html`
3. `application/pdf` Content-Type → `pdf`
4. `text/html` Content-Type → `html`
5. URL extension (`.pdf`, `.html`, `.htm`)
6. Fallback: `txt`

Content bytes dominate because publishers routinely serve HTML login walls at `.pdf` URLs — the URL and even the Content-Type can lie, but the first 4 bytes of the body cannot.

**PDF extraction chain (`_extract_pdf_text`):**
1. `pymupdf` (`fitz`) — fastest, best quality on well-formed and mildly malformed PDFs
2. `pdfminer.six` — battle-tested column-heavy layouts
3. `pypdf` — modern PyPDF2 successor, kept as last resort

First parser to yield non-whitespace text wins. If all three yield empty text, the return is `""` and the 200-char gate treats the download as a failure so the caller can iterate.

**HTML extraction (`_extract_html_text`):**
1. Kill non-content elements (`script`, `style`, `nav`, `header`, `footer`, `aside`, `form`, `button`, `noscript`, `iframe`)
2. Kill junk containers by class/id patterns (`cookie`, `banner`, `signin`, `related`, `sidebar`, `advert`, `promo`, `menu`, `share`, `citation-tools`, `metrics`, `altmetric`)
3. Extract text from the first matching semantic container: `<article>`, `<main>`, `[role="main"]`, `.c-article-body` (Nature/Springer), `.article-body`, `.article__body`, `#article-body`, `#main-content`, `#content`, `<body>`

This cuts ~20–30% nav chrome from Nature/Springer landing pages and starts the text with the actual `Abstract` instead of `Skip to main content / Thank you for visiting nature.com`.

**200-char usable-text gate:**
`_MIN_USABLE_TEXT_CHARS = 200`. Any successful HTTP fetch whose extracted text is under this threshold is treated as a *failed download*: the file is deleted, `downloaded=False` is returned, and `download_with_resolution` iterates to the next candidate. This eliminates the silent "empty text → LLM plausibility fallback" path that used to fabricate `llm_check` "passes" with no source evidence at all.

**`download_with_resolution` cascade:**
1. Try `citation_details.url` directly if present
2. Ask `AcademicPaperFinder.find_urls` for a ranked list of open-access candidates (Unpaywall repository mirrors → publisher PDFs → title fallback)
3. If `INSTITUTIONAL_COOKIES` env var is set, try the DOI landing page with those cookies
4. Return the first candidate that both fetches successfully *and* passes the 200-char extraction gate
5. Along the way, record every attempt (URL, source label, downloaded flag, error) into `result['attempts']` for manifest logging

**API:**
```python
from sourcefinder import TextDownloader
from run_paths import RunPaths

run_paths = RunPaths.for_pdf("pdfs/paper.pdf")
downloader = TextDownloader(run_paths=run_paths, llm_client=llm_client)

# Direct URL — passes only if extraction yields ≥200 chars
result = downloader.download(
    url="https://arxiv.org/pdf/2301.12345.pdf",
    citation_id="paper123_ref_8"
)
# {
#   "downloaded": True,
#   "format": "pdf",
#   "path": ".../citation_paper123_ref_8_text.pdf",
#   "text_content": "Full extracted text...",
#   "error": None
# }

# Iterative resolution — walks candidate list, returns first success
result = downloader.download_with_resolution(
    citation_details,           # CitationDetails | None
    citation_id="paper123_ref_8",
    raw_citation_text="Smith et al. (2023) ... DOI: 10.1234/abc",
)
# Above plus:
# "attempts": [{"url": ..., "source": "direct"|"open_access"|"institutional_cookies",
#               "downloaded": bool, "error": ...}, ...],
# "winning_url": str | None
```

**Features:**
- Magic-byte format detection (URL and Content-Type can be wrong; body bytes can't)
- PDF fallback chain across three libraries; drops `PyPDF2` in favor of `pypdf`
- HTML article-body extraction that strips nav chrome
- 200-char usable-text gate — no more silent empty-source passes
- Multi-candidate cascade via `download_with_resolution`
- Per-attempt cascade logged for manifest reconstruction

### academic_paper_finder.py
Resolves a raw citation string (or DOI) to a ranked list of publicly-accessible PDF/HTML URLs. Used by both `TextDownloader.download_with_resolution` (for cited-qualitative and paper-backed cited-quantitative) and by the dataset-backed quant flow's fallback (when the direct dataset URL fails).

**Resolution cascade:**
1. Regex-extract DOI from citation text (no LLM cost) → try Unpaywall, Semantic Scholar, CrossRef
2. LLM-parsed DOI (catches DOIs the regex misses) → same three APIs
3. LLM-parsed title → Semantic Scholar text search (also recovers the DOI)

**Ranking:** Unpaywall repository mirrors (`host_type == "repository"`) rank ahead of publisher landing pages. Within a host, PDFs (`url_for_pdf`) rank ahead of landing pages (`url_for_landing_page`).

**Explicitly excluded from CrossRef output:** the DOI landing URL (`message.URL`, i.e. `https://doi.org/...`). That URL redirects to the publisher's landing page — almost never a direct download — and its inclusion previously triggered content-negotiation issues (see `DatasetDownloader` Accept header note above). PDF links inside the CrossRef record are still included.

## Configuration

Settings in `config.py`:

```python
# Legacy default download directories (used only when no RunPaths is supplied).
# In production, the active run folder owns these — see run_paths.py.
DATASET_OUTPUT_DIR = "./datasets"
TEXT_OUTPUT_DIR = "./text_sources"

# Thresholds
DATASET_REUSE_THRESHOLD = 0.75
MAX_FILE_SIZE_MB = 500
DOWNLOAD_TIMEOUT = 60  # seconds

# Open-access resolution
UNPAYWALL_EMAIL = os.getenv("UNPAYWALL_EMAIL", "")            # required by Unpaywall ToS
SEMANTIC_SCHOLAR_API_KEY = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "")  # optional
INSTITUTIONAL_COOKIES = os.getenv("INSTITUTIONAL_COOKIES", "")  # JSON: {"domain": {"name": "value"}}

# Endpoints
UNPAYWALL_API = "https://api.unpaywall.org/v2"
SEMANTIC_SCHOLAR_API = "https://api.semanticscholar.org/graph/v1"
CROSSREF_API = "https://api.crossref.org/works"

# Paywall routing
KNOWN_PAYWALL_DOMAINS = [
    "jstor.org", "nature.com", "science.org", "springer.com",
    "wiley.com", "tandfonline.com", "sagepub.com", "elsevier.com",
    "sciencedirect.com", "cell.com", "nejm.org", "thelancet.com",
    "oup.com", "cambridge.org", "annualreviews.org",
]
```

Settings in `text_downloader.py`:
```python
_MIN_USABLE_TEXT_CHARS = 200  # min non-whitespace extracted chars for success
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
# In orchestrator/claim_orchestrator.py

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
- **DatasetDownloader** — non-tabular payload → `{downloaded: false, error: "URL is not tabular data (detected: application/pdf)"}` (or `text/html`, etc.). Caller iterates.
- **TextDownloader** — extraction under 200 usable chars → file deleted from disk, `{downloaded: false, error: "Extraction produced N usable chars (<200); format=..."}`. Caller iterates.
- **TextDownloader** — all three PDF parsers failed → `_extract_pdf_text` returns `""`, then the 200-char gate rejects it. File deleted, download flagged as failed.

## Dependencies

```
requests
pandas
beautifulsoup4       # HTML parsing / article-body extraction
lxml                 # BeautifulSoup fast parser backend
openpyxl             # xlsx read/write
PyMuPDF              # primary PDF extractor
pdfminer.six         # fallback PDF extractor
pypdf                # last-resort PDF extractor (successor to PyPDF2)
PyPDF2               # legacy, retained for callers that import it
playwright           # browser fallback for paywalled searches (optional)
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
