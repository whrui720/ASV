# Agentic Citation Scraper

Hybrid approach for extracting claims and citations from academic PDFs using deterministic parsing + GPT-4o-mini fallback.

## Features

- **Hybrid Citation Parsing**: Tries deterministic regex parsing first, falls back to LLM
- **Smart Claim Extraction**: Uses GPT-4o-mini to identify quantitative and qualitative claims
- **Citation Mapping**: Automatically maps claims to their corresponding citations
- **Cost Tracking**: Monitors API usage and costs
- **Structured Output**: Returns Pydantic models with type safety

## Installation

```bash
# Install dependencies
pip install openai pdfminer.six pydantic tiktoken python-dotenv

# Add your OpenAI API key to geminikey.env
echo "OPENAI_API_KEY=your-key-here" >> ../geminikey.env
```

## Usage

### Command Line

```bash
# Process a PDF
python -m agentic.claim_extractor path/to/paper.pdf

# Output will be saved as paper_claims.json
```

### Python API

```python
from agentic.claim_extractor import HybridClaimExtractor

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

### Step 1: Citation Extraction (Hybrid)
1. Extract text from PDF using pdfminer
2. Locate reference section deterministically
3. Detect citation format (APA, MLA, numeric, etc.)
4. Try deterministic parsing with regex
5. If fails, use GPT-4o-mini as fallback

### Step 2: Claim Extraction (LLM)
1. Chunk document text (excluding references)
2. Process each chunk with GPT-4o-mini
3. Extract claims with structured output
4. Identify claim type (quantitative/qualitative)
5. Detect citation markers in text

### Step 3: Citation Mapping
1. Match citation markers in claims to parsed citations
2. Populate full citation details for each claim
3. Return structured ClaimObject instances

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

### ClaimObject
```json
{
  "claim_id": "claim_0_1",
  "text": "The average energy price increased by 15% last month.",
  "claim_type": "quantitative",
  "citation_found": true,
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
```

## Next Steps (Steps 2-4)

This module implements **Step 1** of the agentic structure:
- ✅ Claim Identification
- ✅ Citation Mapping

**TODO:**
- Step 2: Claim Type Treatment (download datasets/sources)
- Step 3: Claim Validation (generate validation code)
- Step 4: Display (generate report)

## Configuration

Edit [config.py](config.py) to customize:
- Model selection
- Chunking parameters
- Citation patterns
- Cost tracking settings
