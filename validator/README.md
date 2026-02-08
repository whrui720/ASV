# Validator Module

Main orchestrator for the entire ASV pipeline. Coordinates the 3-stage validation process. The validator folder also contains all validation-related tools.

## Architecture

The validator module is the **central orchestrator** that:
1. Receives claims from `hybrid_citation_scraper`
2. Processes them in the correct order
3. Uses `sourcefinder_tools` utilities to find/download sources
4. Validates claims using appropriate methods
5. Outputs results in structured JSON format

## Processing Order

Claims are validated in this specific order for optimal efficiency:

### 1. Qualitative Claims WITHOUT Citations
**Method**: Truth Table + LLM Check
- Check Google Fact Check API for existing fact checks
- Use LLM for plausibility verification
- If EITHER passes → mark as valid
- Fast, no source download needed

### 2. Quantitative Claims WITHOUT Citations
**Method**: Truth Table + LLM Check + Source Finding
- Try truth table and LLM first
- If insufficient confidence, use `sourcefinder_tools` to find datasets
- Mark claims with `originally_uncited=True` and add found source
- Add synthetic citation details
- **Do NOT validate yet** - append to cited quantitative group

### 3. Quantitative Claims WITH Citations (including originally uncited)
**Method**: Python Script Generation + Execution
- Batch by `citation_id`
- Download dataset once per batch (using `dataset_downloader`)
- If download fails → entire batch fails
- Generate Python script to validate claim against dataset
- Execute script with 30s timeout
- Parse JSON output: `{"passed": bool, "confidence": float, "explanation": str}`

### 4. Qualitative Claims WITH Citations
**Method**: RAG + LLM Verification
- Batch by `citation_id`
- Download text source once per batch (using `text_downloader`)
- If download fails → entire batch fails
- Split source into chunks (~500 chars with overlap)
- Use TF-IDF to retrieve top-K most relevant chunks
- LLM verifies claim against retrieved chunks
- Return confidence + supporting quotes

## Modules

### claim_validator.py
Main orchestrator with methods:
- `process_claims()`: Entry point, routes to appropriate handlers
- `_process_uncited_qualitative()`: Truth table + LLM
- `_process_uncited_quantitative()`: Find sources, append to cited group
- `_process_cited_quantitative()`: Batch validation with Python scripts
- `_process_cited_qualitative()`: Batch validation with RAG

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

### quantitative_validator.py
Generate and execute Python scripts:
- Generate script using LLM (prompt includes claim + dataset path)
- Script loads dataset, performs calculations, outputs JSON
- Execute with subprocess (30s timeout)
- Parse JSON output into ValidationResult

### qualitative_validator.py
RAG-based validation:
- Split source text into chunks
- TF-IDF vectorization for retrieval
- Cosine similarity to find top-K chunks
- LLM verifies claim against retrieved context
- Return validation with supporting quotes

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
from validator import ClaimValidator
from models import ClaimObject

# Initialize validator
validator = ClaimValidator(output_dir="validation_results")

# Load claims from claim_extractor
claims = [...]  # List of ClaimObject

# Process all claims
results = validator.process_claims(claims)

# Results are automatically saved to JSON files
# Access results by type:
qual_uncited = results["qualitative_uncited"]
quant_uncited = results["quantitative_uncited"]
qual_cited = results["qualitative_cited"]
quant_cited = results["quantitative_cited"]
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

# Pass to validator
from validator import ClaimValidator
validator = ClaimValidator()
results = validator.process_claims(claims)
```

### Using sourcefinder_tools:
The validator automatically uses sourcefinder utilities:
- `DatasetFinder`: Search for datasets, check reuse
- `TextFinder`: Search for text sources
- `DatasetDownloader`: Download CSV/JSON/Excel
- `TextDownloader`: Download PDF/HTML, extract text

## Claim Ordering Logic

The ordering is designed for efficiency:

1. **Qualitative uncited first**: Fast truth table + LLM check
2. **Quantitative uncited second**: Find sources, don't validate yet
3. **Quantitative cited third**: Batch download + validate (includes found sources)
4. **Qualitative cited last**: Batch download + RAG validation

This ensures:
- Datasets downloaded once per citation
- Originally uncited claims get source info added
- Batch processing maximizes efficiency
- Failed downloads don't block other claim types
