# Hybrid Citation Scraper

Deterministic pipeline with LLM augmentation for extracting claims and citations from academic PDFs. Uses regex-based parsing with GPT-4o-mini fallback for robustness.

## Features

- **Hybrid Citation Parsing**: Tries deterministic regex parsing first, falls back to LLM
- **Smart Claim Extraction**: Uses GPT-4o-mini to identify quantitative and qualitative claims
- **Citation Mapping**: Automatically maps claims to their corresponding citations
- **Cost Tracking**: Monitors API usage and costs
- **Structured Output**: Returns Pydantic models with type safety

## Installation

```bash
# Install dependencies
pip install -r requirements.txt

# Add your OpenAI API key to geminikey.env
echo "OPENAI_API_KEY=your-key-here" >> ../geminikey.env
```

## Usage

### Command Line

```bash
# Process a PDF
python -m hybrid_citation_scraper.claim_extractor path/to/paper.pdf

# Output will be saved as paper_claims.json
```

### Python API

```python
from hybrid_citation_scraper.claim_extractor import HybridClaimExtractor

# Create extractor
extractor = HybridClaimExtractor()

# Process PDF
claims, citations = extractor.process_pdf("paper.pdf")

# Access results
for claim in claims:
    print(f"Claim: {claim.text}")
    print(f"Type: {claim.claim_type}")
    print(f"Citation: {claim.citation_text}")
    print()

# Save to JSON
extractor.save_results("output.json")

# Check costs
cost_info = extractor.llm_client.get_cost_summary()
print(f"Total cost: ${cost_info['total_cost']:.4f}")
```

## Architecture

**Deterministic Pipeline with LLM Augmentation** (not an agentic system)

### Step 1: Citation Extraction (Hybrid: Deterministic → LLM Fallback)
1. Extract text from PDF using LangChain's PyPDFLoader
2. Locate reference section deterministically (keyword search)
3. Detect citation format (APA, MLA, numeric, etc.)
4. Try deterministic regex parsing
5. If fails or invalid, use GPT-4o-mini as fallback

### Step 2: Text Chunking (Sentence-Boundary)
1. Remove reference section from body text
2. Split text on sentence boundaries (`.`, `!`, `?`)
3. Group sentences into ~800 token chunks
4. Add 100-character overlap between chunks to prevent splitting multi-sentence claims
5. Track character positions for accurate location mapping

### Step 3: Claim Extraction (Single-Shot LLM)
1. Process each chunk with GPT-4o-mini
2. Extract claims with structured JSON output (via Pydantic)
3. Classify claim type (quantitative/qualitative)
4. Detect citation markers in text
5. Return typed ClaimObject instances

### Step 4: Citation Mapping (Deterministic)
1. Match citation markers in claims to parsed citations (regex)
2. Populate full citation details for each claim
3. Return final structured results

## Cost Estimates

**GPT-4o-mini Pricing:**
- Input: $0.150 per million tokens
- Output: $0.600 per million tokens

**Typical 10-page academic paper:**
- ~10,000 tokens input
- ~2,000 tokens output
- **Total cost: ~$0.002-0.003** (less than half a cent)

**100 papers: ~$0.20-0.30**

## Output Format

See [models.py](models.py) for complete schemas.

### Complete JSON Output example

The `save_results()` method produces a JSON file with claims, citations, and summary.

**Note:** The JSON structures below correspond to Pydantic models in [models.py](models.py):
- `claims` array → `ClaimObject` model
- `citation_details` object → `CitationDetails` model  
- `location_in_text` object → `LocationInText` model
- `summary` object → No corresponding model (generated dict)
- `citations` dict → Plain dict (not a Pydantic model)

```json
{
  "claims": [
    {
      "claim_id": "claim_0_1",
      "text": "The average energy price increased by 15% last month.",
      "claim_type": "quantitative",
      "citation_found": true,
      "citation_id": "1",
      "citation_text": "[1]",
      "citation_details": {
        "title": "Energy Prices Report",
        "authors": ["Smith, J."],
        "year": 2023,
        "url": "https://example.com/report",
        "doi": "10.1234/example",
        "raw_text": "Smith, J. (2023). Energy Prices Report..."
      },
      "classification": ["objective"],
      "location_in_text": {
        "start": 1234,
        "end": 1289,
        "chunk_id": 0
      }
    }
  ],
  "citations": {
    "1": "Smith, J. (2023). Energy Prices Report. Journal of Economics, 45(3), 123-145. https://doi.org/10.1234/example",
    "2": "Jones, M. et al. (2022). Market analysis. Conference Proceedings, 456-789.",
    "Brown": "Brown, A. (2021). Qualitative study. Publisher Name."
  },
  "summary": {
    "total_claims": 15,
    "quantitative_claims": 8,
    "qualitative_claims": 7,
    "claims_with_citations": 12
  }
}
```

### Citations Dictionary

Maps citation IDs to full citation text for reference and batch processing:

```json
{
  "1": "Full citation text...",
  "2": "Full citation text...",
  "Smith": "Full citation text for author-year citation..."
}
```

**Citation ID Format:**
- Numeric citations: `[1]` → `"1"`, `[23]` → `"23"`
- Author-year: `(Smith, 2020)` → `"Smith"`, `(Jones et al., 2019)` → `"Jones"`

## Pipeline Status

This module implements the **core extraction pipeline**:
- ✅ Hybrid Citation Extraction (deterministic + LLM fallback)
- ✅ Sentence-Boundary Text Chunking with overlap
- ✅ LLM-based Claim Extraction with structured output
- ✅ Deterministic Citation Mapping

**Next stages** (separate modules):
- Step 5: Dataset Discovery (fuzzy search for quantitative claims without citations)
- Step 6: Validation Script Generation (LLM generates Python code to verify claims)
- Step 7: Automated Validation Execution
- Step 8: Report Generation

## Configuration

Edit [config.py](config.py) to customize:
- Model selection
- Chunking parameters
- Citation patterns
- Cost tracking settings
