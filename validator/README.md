# Validator Module

Validation tools used by the ASV pipeline. This folder contains reusable validation primitives; orchestration is handled by the `orchestrator` package.

## Architecture

The validator module provides **validation tools** that:
1. Check claims against fact-check APIs
2. Perform LLM-based plausibility checks
3. Expose reusable primitives for orchestration modules

The claim-ordering pipeline and batch orchestration live in `orchestrator/claim_orchestrator.py`.

## Orchestration Boundary

Processing order and claim batching are implemented in the `orchestrator` package. This module intentionally excludes orchestration classes.

## Modules

### truth_table_checker.py
Query Google Fact Check API:
- Search for existing fact checks
- Parse ClaimReview schema
- Interpret textual ratings (True/False/Mixed)
- Calculate confidence based on rating clarity

### llm_verifier.py
Basic LLM plausibility check:
- Prompt LLM to assess claim plausibility
- Check scientific accuracy, logical consistency
- Return `{plausible, confidence, reasoning}`

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
```python
{
    "claim_id": "paper123_claim_1",
    "claim_type": "quantitative",
    "originally_uncited": false,
    "validated": true,
    "validation_method": "python_script",
    "confidence": 0.92,
    "passed": true,
    "explanation": "Dataset confirms accuracy improvement of 15.3%",
    "sources_used": ["/path/to/dataset.csv"],
    "errors": null
}
```

### Output: ValidationBatch
```python
{
    "citation_id": "paper123_ref_5",
    "citation_text": "[5] Smith et al., 2023",
    "download_successful": true,
    "source_path": "/downloads/smith2023_dataset.csv",
    "claim_results": [
        {...},  # List of ValidationResult
        {...}
    ],
    "batch_notes": "Successfully validated 3 claims"
}
```

## Output Files

Results are saved to separate JSON files by claim type:

- `qualitative_uncited_results.json`: List of ValidationResult
- `quantitative_uncited_results.json`: List of ValidationResult  
- `quantitative_cited_results.json`: List of ValidationBatch
- `qualitative_cited_results.json`: List of ValidationBatch

## Configuration

Key settings in `config.py`:

```python
# Validation thresholds
TRUTH_TABLE_CONFIDENCE_THRESHOLD = 0.7
LLM_CONFIDENCE_THRESHOLD = 0.6

# RAG settings
RAG_TOP_K = 3
RAG_SIMILARITY_THRESHOLD = 0.3

# Script execution
SCRIPT_TIMEOUT_SECONDS = 30

# API keys
GOOGLE_FACT_CHECK_API_KEY = os.getenv('GOOGLE_FACT_CHECK_API_KEY')
```

## Usage

```python
from orchestrator import ClaimValidator
from models import ClaimObject

# Initialize orchestrator
validator = ClaimValidator(output_dir="validation_results")

# Load claims from claim_extractor
claims = [...]  # List of ClaimObject

# Process all claims
results = validator.process_claims(claims)
```

## Dependencies

Required packages:
```
openai
scikit-learn
numpy
pandas
requests
```

## Error Handling

### Batch Processing
- If dataset/text download fails → entire batch fails
- All claims in batch get validation_method but passed=False
- Error message stored in ValidationResult.errors

### Script Execution
- 30-second timeout per script
- Subprocess captures stdout/stderr
- JSON parsing errors → validation failed

### RAG Processing
- Fallback to first K chunks if TF-IDF fails
- Empty source text → validation failed
- LLM errors → validation failed with error message

## Integration with Other Modules

### From hybrid_citation_scraper:
```python
from hybrid_citation_scraper import ClaimExtractor

# Extract claims
extractor = ClaimExtractor(api_key="...")
claims = extractor.process_pdf("paper.pdf")

# Pass to orchestrator
from orchestrator import ClaimValidator
validator = ClaimValidator()
results = validator.process_claims(claims)
```

### Using sourcefinder_tools:
The orchestrator automatically uses sourcefinder utilities:
- `DatasetFinder`: Search for datasets, check reuse
- `TextFinder`: Search for text sources
- `DatasetDownloader`: Download CSV/JSON/Excel
- `TextDownloader`: Download PDF/HTML, extract text

## Claim Ordering Logic

The ordering logic remains unchanged and now lives in `orchestrator/claim_orchestrator.py`.
