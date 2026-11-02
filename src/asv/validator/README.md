# asv.validator — Verification Backends

Validation tools used by the ASV pipeline (`src/asv/validator/`). This folder contains reusable validation primitives; orchestration is handled by the `asv.orchestrator` package.

## Architecture

The validator module provides **validation tools** that:
1. Verify claims against retrieved source text
2. Refuse to verify when there is no usable source — and say why
3. Expose reusable primitives for orchestration modules

The claim-ordering pipeline and batch orchestration live in `orchestrator/claim_orchestrator.py`.

## Orchestration Boundary

Processing order and claim batching are implemented in the `orchestrator` package. This module intentionally excludes orchestration classes.

## Modules

### llm_verifier.py
Source-grounded verification only. The plausibility check (`verify_claim`) was
deleted in Tier 0.1 — see `docs/TIER0_PLAN.md` §3. It asked a small model whether
a sentence *sounded* right, and on the reference corpus produced 217 of 224
"passes" with `sources_used: []`. The callers and the primitive both went; keeping
the primitive would have guaranteed its return.

`verify_claim_against_source(claim, source_text, source_url)`:
- Chunk the source and retrieve the top-K passages by TF-IDF cosine similarity
- Ask the model for a graded verdict against *those passages only*
- **Verify every quote it returns actually appears in them** — if none does, the
  verdict is discarded in favour of `not_checkable(evidence_unverifiable)`
- Return `{verdict, not_checkable_reason, confidence, explanation, evidence, rag_chunks}`

Nothing clearing the retrieval threshold returns `not_checkable(retrieval_empty)`,
not a failed claim: no passage was found, which says nothing about the claim.

### python_script_validator.py
Dataset-backed quantitative claims only. The strong-tier model writes a pandas
script, which is saved to `runs/*/generated_scripts/validate_{claim_id}.py` and run
with a 30-second timeout; the JSON it prints is the evidence for the verdict.

**Not sandboxed.** The script runs as a plain `subprocess.run` that inherits the
parent's environment (API keys included), network and filesystem. Don't run it on
untrusted PDFs. `VALUE_PROPOSITION.md` §7 Tier 4 recommends replacing this path
with deterministic checks; `NOTEBOOK_SANDBOX_PLAN.md` proposes containing it. Neither
has been built.

## Orchestration Modules

Moved to `orchestrator/`:
- `claim_orchestrator.py`
- `process_quantitative.py`
- `process_qualitative.py`

## Data Models

### Input: ClaimObject
```python
{
    "claim_id": "paper123_claim_1",
    "text": "The accuracy improved by 15%",
    "claim_type": "quantitative",
    "citation_found": true,
    "citation_id": "paper123_ref_5",
    "citation_text": "[5] Smith et al., 2023",
    "citation_details": {...},
    "is_original": false,
    "originally_uncited": false,  # Set to True if source was found by validator
    "found_source": None  # Populated if source was found
}
```

### Output: ValidationResult
Trimmed; see `src/asv/core/models.py` for the full model and `docs/QUICKSTART.md`
for complete examples.
```python
{
    "claim_id": "paper123_claim_1",
    "claim_type": "qualitative",
    "validation_method": "rag_search",
    "verdict": "partially_substantiated",   # see core/verdicts.py
    "not_checkable_reason": None,           # always set when verdict == not_checkable
    "confidence": 0.74,                     # always None when verdict == not_checkable
    "explanation": "The source reports this in a murine model; the claim states it of patients.",
    "evidence": [{"quote": "...", "verified_verbatim": True, "source_url": "..."}],
    "source_url": "https://europepmc.org/article/MED/1234567",
    "flags": [],                            # e.g. cited_source_retracted
    "passed": False                         # deprecated, computed: verdict == substantiated
}
```

### Output: ValidationBatch
```python
{
    "citation_id": "paper123_ref_5",
    "citation_text": "[5] Smith et al., 2023",
    "download_successful": true,     # bytes arrived
    "judgeable": true,               # ...and the content gate rated them full text
    "content_quality": "full_text",  # full_text | abstract_only | paywall_interstitial | rejected
    "source_path": "runs/paper123__20260101_120000/text_sources/citation_paper123_ref_5_text.xml",
    "claim_results": [
        {...},  # List of ValidationResult
        {...}
    ],
    "batch_notes": "Successfully validated 3 claims"
}
```

## Output Files

Results are saved to `runs/{pdf_stem}__{YYYYMMDD_HHMMSS}/validation_results/` as separate JSON files by claim type:

- `qualitative_uncited_results.json`: List of ValidationResult
- `quantitative_uncited_results.json`: List of ValidationResult
- `quantitative_cited_results.json`: List of ValidationBatch
- `qualitative_cited_results.json`: List of ValidationBatch

## Configuration

Key settings in `config.py`:

```python
# Validation thresholds
LLM_VERIFIER_CONFIDENCE_THRESHOLD = 0.8
DATASET_REUSE_CONFIDENCE = 0.75

# LLM behavior
LLM_TEMPERATURE = 0.2
LLM_MAX_RETRIES = 3

# RAG settings
RAG_TOP_K = 3
RAG_TOP_K_CHUNKS = 3
RAG_MIN_CHUNK_LENGTH = 50
RAG_MAX_CHUNK_LENGTH = 500
RAG_SIMILARITY_THRESHOLD = 0.15  # lowered from 0.3 — see note below

# Script execution. Dead config: python_script_validator.py hardcodes timeout=30
# and imports none of these (NOTEBOOK_SANDBOX_PLAN.md §1).
SCRIPT_TIMEOUT = 60
SCRIPT_TIMEOUT_SECONDS = 30
SCRIPT_MAX_OUTPUT_LENGTH = 10000

# Tier 0.5 — evidence verification
QUOTE_VERIFICATION_THRESHOLD = 92   # rapidfuzz partial_ratio, 0-100
QUOTE_VERIFICATION_MIN_CHARS = 20   # shorter "quotes" match anything
SOURCE_VERIFICATION_PROMPT_VERSION = "..."   # recorded on every result
```

### `RAG_SIMILARITY_THRESHOLD` note

The cosine-similarity floor for a TF-IDF-retrieved chunk to be forwarded to the LLM. Was `0.3`; lowered to `0.15` after empirical testing showed that ~7 batches per run were silently failing with "No relevant chunks found in source" because legitimate matches sat just below the old threshold. Lowering it lets more chunks reach the LLM, which then decides for itself whether the evidence supports the claim.

The `RAG_TOP_K = 3` cap still bounds the LLM's context to at most 3 chunks per claim, so lowering the threshold doesn't grow prompt size unboundedly — it just reduces false negatives at the retrieval step.

## Usage

```python
from asv.orchestrator import ClaimOrchestrator
from asv.core.run_paths import RunPaths
from asv.core.models import ClaimObject

# Initialize the per-PDF run folder + orchestrator
run_paths = RunPaths.for_pdf("pdfs/paper.pdf")
orchestrator = ClaimOrchestrator(run_paths=run_paths)

# Load claims from claim_extractor
claims = [...]  # List of ClaimObject
citations = {...}  # Dict[str, str]

# Process all claims (writes results under run_paths.validation_results)
results = orchestrator.process_claims(claims, citations)
```

## Dependencies

Required packages:
```
google-genai
scikit-learn
rapidfuzz
numpy
pandas
requests
```

## Error Handling

Every failure is an abstention with a reason, never a failed claim
(`docs/TIER0_PLAN.md`; reason codes in `src/asv/core/verdicts.py`):

| Situation | Result |
|---|---|
| No candidate URL resolved | `not_checkable(source_not_resolved)` |
| Candidates found, every fetch failed | `not_checkable(source_download_failed)` |
| Fetched, but the content gate says abstract / login wall | `not_checkable(abstract_only)` / `not_checkable(paywall_interstitial)` |
| No chunk clears `RAG_SIMILARITY_THRESHOLD` | `not_checkable(retrieval_empty)` |
| Model's quotes not found in the retrieved text | `not_checkable(evidence_unverifiable)`; unverified quotes kept in `validation_metadata` |
| TF-IDF vectorisation raises | soft fallback to the first K chunks, unranked |
| Script timeout (30 s) / unparseable script output | `not_checkable(validation_error)`, details on `errors` |

## Integration with Other Modules

### From asv.extraction:
```python
from asv.extraction.claim_extractor import HybridClaimExtractor
from asv.orchestrator import ClaimOrchestrator
from asv.core.run_paths import RunPaths

run_paths = RunPaths.for_pdf("pdfs/paper.pdf")

# Extract claims
extractor = HybridClaimExtractor()
claims, citations = extractor.process_pdf("pdfs/paper.pdf")
extractor.save_results(pdf_path="pdfs/paper.pdf", run_paths=run_paths)

# Pass to orchestrator
orchestrator = ClaimOrchestrator(run_paths=run_paths)
results = orchestrator.process_claims(claims, citations)
```

### Using sourcefinder:
The orchestrator automatically uses sourcefinder utilities:
- `DatasetFinder`: Search for datasets, check reuse
- `AcademicPaperFinder`: Resolve a citation to ranked full-text candidates
- `DatasetDownloader`: Download CSV/JSON/Excel
- `TextDownloader`: Download PDF/HTML, extract text

## Claim Ordering Logic

The ordering logic remains unchanged and now lives in `orchestrator/claim_orchestrator.py`.
