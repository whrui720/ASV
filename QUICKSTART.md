# Quick Start Guide

## Installation

1. **Install dependencies:**
```bash
pip install -r requirements.txt
```

2. **Set up environment variables:**
Create a `.env` file in the project root:
```bash
GEMINI_API_KEY=your_gemini_api_key_here
GOOGLE_FACT_CHECK_API_KEY=your_google_key_here  # Optional

```

## Basic Usage

### Complete Pipeline (Extract + Validate) — recommended

```bash
python scripts/run_pipeline.py pdfs/research_paper.pdf
```

This creates a fresh `runs/{pdf_stem}__{YYYYMMDD_HHMMSS}/` folder and writes every artifact (claims, sources, scripts, results, run summary, log) under it.

### Programmatic usage

```python
from hybrid_citation_scraper.claim_extractor import HybridClaimExtractor
from orchestrator import ClaimOrchestrator
from run_paths import RunPaths

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
from orchestrator import ClaimOrchestrator
from run_paths import RunPaths

run_paths = RunPaths.from_existing("runs/research_paper__20260101_120000")
orchestrator = ClaimOrchestrator(run_paths=run_paths)
claims, citations = ClaimOrchestrator.load_claims_from_json(str(run_paths.claims_json()))
results = orchestrator.process_claims(claims, citations)
```

## Output Files

After validation, the run folder `runs/{pdf_stem}__{YYYYMMDD_HHMMSS}/` contains 4 JSON files under `validation_results/`:

### 1. qualitative_uncited_results.json
```json
[
  {
    "claim_id": "claim_0_1",
    "claim_type": "qualitative",
    "originally_uncited": false,
    "validated": true,
    "validation_method": "truth_table+llm_check",
    "confidence": 0.85,
    "passed": true,
    "explanation": "Truth Table: Verified. LLM Check: Plausible.",
    "sources_used": ["https://factcheck.com/..."],
    "errors": null
  }
]
```

### 2. quantitative_uncited_results.json
Similar structure to qualitative_uncited_results.json

### 3. quantitative_cited_results.json
```json
[
  {
    "citation_id": "paper123_ref_5",
    "citation_text": "[5] Smith et al., 2023",
    "download_successful": true,
    "source_path": "runs/paper123__20260101_120000/datasets/citation_paper123_ref_5_dataset.csv",
    "claim_results": [
      {
        "claim_id": "claim_3_1",
        "claim_type": "quantitative",
        "originally_uncited": false,
        "validated": true,
        "validation_method": "python_script",
        "confidence": 0.95,
        "passed": true,
        "explanation": "Dataset confirms accuracy improvement of 15.3%",
        "sources_used": ["runs/paper123__20260101_120000/datasets/citation_paper123_ref_5_dataset.csv"],
        "errors": null
      }
    ],
    "batch_notes": "Successfully validated 3 claims"
  }
]
```

### 4. qualitative_cited_results.json
Similar batch structure to quantitative_cited_results.json

## Access Results

```python
# After validation
results = orchestrator.process_claims(claims, citations)

# Qualitative uncited (List of ValidationResult)
for result in results["qualitative_uncited"]:
    print(f"Claim {result.claim_id}: {'PASSED' if result.passed else 'FAILED'}")
    print(f"  Confidence: {result.confidence}")
    print(f"  Method: {result.validation_method}")

# Quantitative cited (List of ValidationBatch)
for batch in results["quantitative_cited"]:
    print(f"\nCitation: {batch.citation_id}")
    print(f"Download: {'SUCCESS' if batch.download_successful else 'FAILED'}")

    for claim_result in batch.claim_results:
        status = 'PASSED' if claim_result.passed else 'FAILED'
        print(f"  Claim {claim_result.claim_id}: {status}")
        print(f"    Explanation: {claim_result.explanation}")
```

## Configuration

### Adjust Validation Thresholds

Edit `validator/config.py`:
```python
TRUTH_TABLE_CONFIDENCE_THRESHOLD = 0.7  # Lower = more lenient
LLM_CONFIDENCE_THRESHOLD = 0.6
RAG_SIMILARITY_THRESHOLD = 0.3  # Lower = retrieve more chunks
SCRIPT_TIMEOUT_SECONDS = 30  # Script execution timeout
```

### Adjust Claim Extraction

Edit `hybrid_citation_scraper/config.py`:
```python
CHUNK_SIZE = 800  # Larger = fewer API calls but less precise
CHUNK_OVERLAP = 100  # Overlap between chunks
REFERENCE_SECTION_THRESHOLD = 0.7  # 70% through document
```

### Adjust Dataset Reuse

Edit `sourcefinder/config.py`:
```python
DATASET_REUSE_CONFIDENCE_THRESHOLD = 0.75  # Higher = less reuse
DOWNLOAD_TIMEOUT = 30  # Seconds
```

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
- Check timeout settings in `sourcefinder/config.py`

### "Script execution timeout"
Increase timeout in `validator/config.py`:
```python
SCRIPT_TIMEOUT_SECONDS = 60  # Increase from 30 to 60
```

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
from hybrid_citation_scraper.claim_extractor import HybridClaimExtractor
from orchestrator import ClaimOrchestrator
from run_paths import RunPaths

run_paths = RunPaths.for_pdf("pdfs/paper.pdf")

# Extract and validate
extractor = HybridClaimExtractor()
claims, citations = extractor.process_pdf("pdfs/paper.pdf")
extractor.save_results(pdf_path="pdfs/paper.pdf", run_paths=run_paths)

orchestrator = ClaimOrchestrator(run_paths=run_paths)
results = orchestrator.process_claims(claims, citations)

# Count passed/failed
passed = sum(1 for r in results["qualitative_uncited"] if r.passed)
total = len(results["qualitative_uncited"])
print(f"Qualitative uncited: {passed}/{total} passed")
```

### Example 2: Filter Only Quantitative Claims
```python
from run_paths import RunPaths

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
from validator import TruthTableChecker, LLMVerifier

# Use individual validators
truth_checker = TruthTableChecker()
llm_verifier = LLMVerifier(llm_client)

for claim in claims:
    # Check truth table
    tt_result = truth_checker.check_claim(claim.text)
    
    if not tt_result['found']:
        # Fallback to LLM
        llm_result = llm_verifier.verify_claim(claim.text)
        print(f"LLM: {llm_result['plausible']}")
```

## Cost Estimates

**Gemini pricing:**
- Input: $0.150 per million tokens
- Output: $0.600 per million tokens

**Typical costs:**
- 10-page paper extraction: ~$0.002-0.003
- Validation (100 claims): ~$0.01-0.02
- **Total per paper: ~$0.015-0.025**

**100 papers: ~$1.50-2.50**

## Next Steps

1. Test with sample PDFs
2. Integrate real APIs (Kaggle, Scholar, arXiv)
3. Add error handling and retry logic
4. Build web interface for results
5. Add progress tracking for large batches

## Support

See module-specific documentation:
- [Claim Extraction](hybrid_citation_scraper/README.md)
- [Orchestrator](orchestrator/README.md)
- [Validator](validator/README.md)
- [Sourcefinder](sourcefinder/README.md)
