# Quick Start Guide

## Installation

1. **Install the package and dependencies:**
```bash
pip install -e ".[dev]"      # or: pip install -e .   (runtime only)
playwright install chromium  # browser fallback for paywalled sources
```

2. **Set up credentials.** Copy `.env.example` to `.env` and fill it in, or start the web
UI (below) and use the form at `/config`, which writes the same file and explains what
each field unlocks. The minimum worth running with:
```bash
GEMINI_API_KEY=...       # required
UNPAYWALL_EMAIL=...      # any real address; without it the Unpaywall step is skipped
```
Every other key is optional and raises the share of sources ASV can read in full. See
`.env.example` for the list, or run `/credentials` in Claude Code for a walkthrough.

## Basic Usage

### Complete Pipeline (Extract + Validate) — recommended

```bash
python scripts/run_pipeline.py pdfs/research_paper.pdf
```

This creates a fresh `runs/{pdf_stem}__{YYYYMMDD_HHMMSS}/` folder and writes every artifact (claims, sources, scripts, results, run summary, log) under it.

### Programmatic usage

```python
from asv.extraction.claim_extractor import HybridClaimExtractor
from asv.orchestrator import ClaimOrchestrator
from asv.core.run_paths import RunPaths

run_paths = RunPaths.for_pdf("pdfs/research_paper.pdf")

# Step 1: Extract claims from PDF
extractor = HybridClaimExtractor()
claims, citations = extractor.process_pdf("pdfs/research_paper.pdf")
extractor.save_results(pdf_path="pdfs/research_paper.pdf", run_paths=run_paths)
print(f"Extracted {len(claims)} claims")

# Step 2: Validate all claims
orchestrator = ClaimOrchestrator(run_paths=run_paths)
results = orchestrator.process_claims(claims, citations)

print("Validation complete!")
print(f"Results saved under {run_paths.root}")
```

### Validate Pre-Extracted Claims

```bash
# Reattach to an existing run folder (or synthesize one if needed)
python scripts/run_orchestrator.py runs/research_paper__20260101_120000/citations/research_paper_claims.json
```

Programmatic equivalent:

```python
from asv.orchestrator import ClaimOrchestrator
from asv.core.run_paths import RunPaths

run_paths = RunPaths.from_existing("runs/research_paper__20260101_120000")
orchestrator = ClaimOrchestrator(run_paths=run_paths)
claims, citations = ClaimOrchestrator.load_claims_from_json(str(run_paths.claims_json()))
results = orchestrator.process_claims(claims, citations)
```

## Run the Web UI Locally

The frontend (`apps/web/`) reads run data written by the pipeline above, so generate at least one run first (e.g. `python scripts/run_pipeline.py pdfs/hsv_cancer.pdf`).

### Option A: Dev mode (hot reload, recommended while iterating)

Two terminals:

```bash
# Terminal 1 — backend on :8000
uvicorn apps.api.main:app --reload --port 8000
```

```bash
# Terminal 2 — frontend on :5173
cd apps/web
npm install      # first time only
npm run dev
```

Open **http://localhost:5173** — Vite proxies `/api/*` to the backend on `:8000` (see `apps/web/vite.config.ts`).

### Option B: One-process mode (closer to prod)

Builds the frontend once, then a single FastAPI process serves both the API and the static bundle:

```bash
python scripts/run_webapp.py --reload
```

Open **http://localhost:8000**. Use `--no-build` to skip rebuilding if `apps/web/dist/` already exists, or `--port` to change the port.

### Sanity check

```bash
curl http://127.0.0.1:8000/api/health   # -> {"ok": true}
```

If `apps/web`'s API types drift from the backend, regenerate them (backend must be running on `:8000`):
```bash
cd apps/web && npm run gen-types
```

## Output Files

After validation, the run folder `runs/{pdf_stem}__{YYYYMMDD_HHMMSS}/` contains 4 JSON files under `validation_results/`:

### 1. qualitative_uncited_results.json

A claim with no citation has no source to check against, so it is never judged —
see `docs/TIER0_PLAN.md` §3. The reason code is the actionable part.

```json
[
  {
    "claim_id": "claim_0_1",
    "claim_type": "qualitative",
    "originally_uncited": false,
    "validated": false,
    "validation_method": "not_checkable",
    "verdict": "not_checkable",
    "not_checkable_reason": "no_source_available",
    "confidence": null,
    "passed": false,
    "explanation": "No citation was attached to this claim in the source document, so there is no source to check it against. ASV does not judge claims from model priors.",
    "evidence": [],
    "source_url": null,
    "flags": [],
    "sources_used": [],
    "errors": null
  }
]
```

A judged claim instead looks like this — note that the four non-abstention
verdicts cannot be written without a verbatim-verified quote and a resolvable URL:

```json
{
  "verdict": "partially_substantiated",
  "not_checkable_reason": null,
  "confidence": 0.74,
  "explanation": "The source reports this in a murine model; the claim states it of patients.",
  "evidence": [
    {
      "quote": "in a murine model, titres peaked at 24 hours post-infection",
      "role": "supporting",
      "source_url": "https://europepmc.org/article/MED/1234567",
      "retrieval_score": 0.41,
      "char_start": 18422,
      "char_end": 18480,
      "verified_verbatim": true
    }
  ],
  "source_url": "https://europepmc.org/article/MED/1234567",
  "content_quality": "full_text",
  "flags": ["cited_source_retracted"]
}
```

### 2. quantitative_uncited_results.json
Similar structure to qualitative_uncited_results.json

### 3. quantitative_cited_results.json
A list of `ValidationBatch`, one per citation. `download_successful` says bytes arrived;
`judgeable` says the content gate rated them full text. Only judgeable batches get
verdicts.
```json
[
  {
    "citation_id": "23",
    "citation_text": "[23] Smith et al., 2023",
    "download_successful": true,
    "judgeable": false,
    "content_quality": "abstract_only",
    "claim_results": [
      {
        "claim_id": "claim_3_1",
        "claim_type": "quantitative",
        "validation_method": "rag_search",
        "verdict": "not_checkable",
        "not_checkable_reason": "abstract_only",
        "confidence": null,
        "explanation": "Only the abstract of the cited source could be obtained ...",
        "evidence": [],
        "source_url": "https://doi.org/10.1234/abc"
      }
    ],
    "batch_notes": "..."
  }
]
```
Dataset-backed batches have the same shape with `validation_method: "python_script"`.
`passed` still appears on every result but is deprecated: it is computed as
`verdict == "substantiated"`. Read `verdict`.

### 4. qualitative_cited_results.json
Similar batch structure to quantitative_cited_results.json

## Access Results

```python
# After validation
results = orchestrator.process_claims(claims, citations)

# Qualitative uncited (List of ValidationResult)
for result in results["qualitative_uncited"]:
    print(result.claim_id, result.verdict.value, result.not_checkable_reason)

# Quantitative cited (List of ValidationBatch)
for batch in results["quantitative_cited"]:
    print(f"\nCitation: {batch.citation_id}")
    print(f"Downloaded: {batch.download_successful}  judgeable: {batch.judgeable}")

    for r in batch.claim_results:
        print(f"  {r.claim_id}: {r.verdict.value} {r.not_checkable_reason or ''}")
        for span in r.evidence:
            print(f"    quote: {span.quote}")
```

## Configuration

### Adjust Validation Thresholds

Edit `src/asv/validator/config.py`:
```python
LLM_VERIFIER_CONFIDENCE_THRESHOLD = 0.8
DATASET_REUSE_CONFIDENCE = 0.75

RAG_TOP_K = 3                                # Max chunks fed to the LLM
RAG_SIMILARITY_THRESHOLD = 0.15              # Lower = more chunks pass to the LLM
RAG_MIN_CHUNK_LENGTH = 50
RAG_MAX_CHUNK_LENGTH = 500

QUOTE_VERIFICATION_THRESHOLD = 92            # rapidfuzz partial_ratio a quote must reach
LLM_TEMPERATURE = 0.2
LLM_MAX_RETRIES = 3
```

`RAG_SIMILARITY_THRESHOLD` is the cosine-similarity floor for a chunk to reach the LLM. It was `0.3` and was lowered to `0.15` after empirical testing showed that many quantitative claims had legitimate matches sitting just below the old threshold. Raising it makes the pipeline stricter (fewer chunks reach the LLM); lowering it gives the LLM more context to reason over but risks noise.

### Adjust Claim Extraction

Edit `src/asv/extraction/config.py`:
```python
CHUNK_SIZE = 800     # Larger = fewer API calls but less precise
CHUNK_OVERLAP = 100  # Overlap between chunks
```

### Adjust Source Finding / Downloading

Edit `src/asv/sourcefinder/config.py`:
```python
DATASET_REUSE_THRESHOLD = 0.75  # Higher = less dataset reuse
DOWNLOAD_TIMEOUT = 60           # Seconds
MAX_FILE_SIZE_MB = 500
```

The content-quality gate's thresholds (`CQ_*`, starting with `CQ_MIN_USABLE_CHARS = 200`)
are in the same file. Below the floor a fetch is rejected and the next candidate is tried;
above it, the classifier decides whether the text is full text, an abstract, or an access
wall, and only full text is judged. The thresholds are uncalibrated; use
`scripts/calibrate_content_quality.py` rather than tuning them by hand.

## Troubleshooting

### "No API key found"
Make sure your `.env` file exists and contains:
```
GEMINI_API_KEY=...
```

### "sklearn import error"
Install scikit-learn:
```bash
pip install scikit-learn
```

### "Dataset download failed"
- Check the citation URL is valid
- Check network connection
- Check timeout settings in `src/asv/sourcefinder/config.py`

### "URL is not tabular data (detected: application/pdf)"
`DatasetDownloader` explicitly rejects non-tabular payloads. This is normal — the orchestrator's cascade will move to the next candidate URL. If every candidate for a batch is a PDF, the batch is genuinely paper-backed (not dataset-backed); if the batch is quantitative cited, it will be routed through `_process_paper_backed_quant` (RAG) instead of the strict script-validator path.

### "Unusable content: only N usable characters"
`TextDownloader` treats short extractions as failures. Common causes:
- The URL served an HTML login-wall (Wiley/ASM/OUP paywalls do this even to `.pdf` URLs)
- PDF was scanned images with no embedded text — none of `pymupdf`, `pdfminer.six`, or `pypdf` could extract anything
- HTML page had no `<article>`/`<main>` container after stripping nav chrome

If the orchestrator iterates through every candidate and every one fails this way, the batch's `download_successful=False` and its claims are `not_checkable(source_download_failed)`.

### Most cited claims are `not_checkable(abstract_only)`
The source was fetched, but only as an abstract or landing page, and ASV doesn't judge a
claim against an abstract. More credentials (`UNPAYWALL_EMAIL`, `CORE_API_KEY`, publisher
TDM keys, `EZPROXY_HOST`) or the browser login flow give it more routes to full text.

### Paywalled sources — using the Playwright login flow
After the up-front resolution pass, if any resolved candidate URL is on a `KNOWN_PAYWALL_DOMAINS` host (see `src/asv/sourcefinder/config.py`), the orchestrator opens a visible Chromium window with a tab per domain at startup and prints:

```
[ASV] Please log in to the following sites in the browser window:
  nature.com, sciencedirect.com
Press Enter here when done to continue the pipeline...
```

Log in normally in each tab (SSO, institutional proxy, whatever your library uses), then press Enter in the terminal. The pipeline then:
1. Snapshots every cookie in the browser context via `BrowserSearcher.export_cookies()`.
2. Injects them into `TextDownloader.session`, `AcademicPaperFinder._session`, and `DatasetDownloader.session` — so subsequent `requests.get()` calls carry your session.
3. Mirrors them into `AcademicPaperFinder._inst_cookies` by domain so `fetch_with_cookies()` finds them.
4. If a fetch still fails, `download_with_resolution` retries each attempted URL through `BrowserSearcher.download_url()`, which uses Playwright's `APIRequestContext` (shares storage state with the browser — closest thing to a real navigation).

Requires `BROWSER_HEADLESS = False` in `src/asv/sourcefinder/config.py` (the default). Logins are not yet persisted between runs, so expect the prompt on every run. When the run is launched from the web UI, the prompt appears there (an `awaiting_login` event) instead of in the terminal. `INSTITUTIONAL_COOKIES` remains as an escape hatch for headless use, but it needs hand-copied cookies that expire.

### `not_checkable(retrieval_empty)`
The TF-IDF retriever found nothing above `RAG_SIMILARITY_THRESHOLD` in the downloaded text. This is reported as a retrieval failure, not as evidence against the claim. TF-IDF misses paraphrase; lowering the threshold in `src/asv/validator/config.py` lets more chunks through at the cost of noise.

### "Script execution timeout"
The 30 s timeout is hardcoded in `src/asv/validator/python_script_validator.py`; the
`SCRIPT_TIMEOUT*` values in `validator/config.py` are not read.

### "Out of memory"
Process claims in smaller batches:
```python
# Process first 50 claims
subset = claims[:50]
results = orchestrator.process_claims(subset, citations)
```

## Examples

### Example 1: Process Single Paper
```python
from asv.extraction.claim_extractor import HybridClaimExtractor
from asv.orchestrator import ClaimOrchestrator
from asv.core.run_paths import RunPaths

run_paths = RunPaths.for_pdf("pdfs/paper.pdf")

# Extract and validate
extractor = HybridClaimExtractor()
claims, citations = extractor.process_pdf("pdfs/paper.pdf")
extractor.save_results(pdf_path="pdfs/paper.pdf", run_paths=run_paths)

orchestrator = ClaimOrchestrator(run_paths=run_paths)
results = orchestrator.process_claims(claims, citations)

# Tally verdicts across the cited groups
from collections import Counter
tally = Counter(
    r.verdict.value
    for group in ("qualitative_cited", "quantitative_cited")
    for batch in results[group]
    for r in batch.claim_results
)
print(tally)
```

### Example 2: Filter Only Quantitative Claims
```python
from asv.extraction.claim_extractor import HybridClaimExtractor
from asv.orchestrator import ClaimOrchestrator
from asv.core.run_paths import RunPaths

run_paths = RunPaths.for_pdf("pdfs/paper.pdf")
extractor = HybridClaimExtractor()
all_claims, citations = extractor.process_pdf("pdfs/paper.pdf")

# Filter quantitative only
quant_claims = [c for c in all_claims if c.claim_type == "quantitative"]

# Validate
orchestrator = ClaimOrchestrator(run_paths=run_paths)
results = orchestrator.process_claims(quant_claims, citations)
```

### Example 3: Custom Validation Pipeline
```python
from asv.validator import LLMVerifier

llm_verifier = LLMVerifier(llm_client)

for claim, source_text, source_url in pairs:
    result = llm_verifier.verify_claim_against_source(
        claim.text, source_text, source_url=source_url,
    )
    print(result["verdict"], result.get("not_checkable_reason"))
    for span in result["evidence"]:
        print("  ", span.quote)
```

There is no source-free path. `LLMVerifier` has no `verify_claim`: a claim with
no source is reported as `not_checkable`, never scored against model priors.

## Cost

Not measured yet. `LLMClient.get_cost_summary()` applies one flat price to every model
tier (including Gemini Pro), and the orchestration stage isn't costed at all, so any
figure it prints is unreliable (`docs/VALUE_PROPOSITION.md` §7, Tier 3.4).

## Support

See module-specific documentation:
- [Claim Extraction](../src/asv/extraction/README.md)
- [Orchestrator](../src/asv/orchestrator/README.md)
- [Validator](../src/asv/validator/README.md)
- [Sourcefinder](../src/asv/sourcefinder/README.md)

Plans, analyses and their status: [docs/README.md](README.md).
