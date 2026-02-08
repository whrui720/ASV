# Hybrid Citation Scraper

**Stage 1 of the ASV Pipeline:** Extracts claims and citations from academic PDFs using a deterministic pipeline with LLM augmentation.

## What It Does

Takes a PDF research paper and extracts:
- **Claims**: All objective, fact-based statements (quantitative and qualitative)
- **Citations**: References to external sources
- **Mappings**: Which claims cite which sources
- **Classification**: Quantitative vs qualitative, original vs cited

Subjective claims (opinions, interpretations) are automatically filtered out. The output is a structured, sorted list of objective claims ready for validation (Stage 2).

## Quick Start

### Installation
```bash
pip install -r requirements.txt
```

### Basic Usage

```python
from hybrid_citation_scraper.claim_extractor import HybridClaimExtractor

# Initialize
extractor = HybridClaimExtractor()

# Extract claims from PDF (returns sorted list of ClaimObject)
claims = extractor.process_pdf("research_paper.pdf")

# Save to JSON
extractor.save_results("output.json")

# Check API costs
cost = extractor.llm_client.get_cost_summary()
print(f"Cost: ${cost['total_cost']:.4f}")
```

### Simple Example

```python
extractor = HybridClaimExtractor()
claims = extractor.process_pdf("paper.pdf")

# Print all claims
for claim in claims:
    print(f"\n{claim.claim_type.upper()}: {claim.text}")
    if claim.citation_found:
        print(f"  → Cites: {claim.citation_text}")
    if claim.is_original:
        print(f"  → Original contribution from this paper")
```


## Input & Output

### Input
- **PDF file path** (string)
- **OpenAI API key** (via environment variable)

### Output 

**Saves JSON file with:**
```json
{
  "claims": [...],        // List of ClaimObject
  "citations": {...},     // Dict of citation_id -> full citation text
  "summary": {...}        // Stats (total claims, types, etc.)
}
```

**Primary:** List of `ClaimObject`, sorted (see "Claim Ordering" below) for efficient validation

### ClaimObject Structure

Each claim has:
```python
{
    "claim_id": str,              # Unique ID (e.g., "claim_0_1")
    "text": str,                  # Full claim text
    "claim_type": str,            # "quantitative" or "qualitative"
    "citation_found": bool,       # True if claim has citation
    "citation_id": str | None,    # ID of citation (e.g., "1", "Smith")
    "citation_text": str | None,  # Citation marker (e.g., "[1]")
    "citation_details": dict | None,  # Full citation info
    "is_original": bool,          # True if paper's own contribution
    "location_in_text": dict      # Character positions in PDF
}
```

**Note:** All extracted claims are objective and fact-based. Subjective claims are filtered out during extraction.

#### Field Definitions

**Claim Types:**
- **quantitative**: Contains numbers, statistics, measurements, percentages
- **qualitative**: Descriptive statements without specific numeric data

**Citation Fields:**
- **citation_found**: Whether claim references an external source
- **citation_id**: Unique identifier (`"1"`, `"Smith"`, etc.)
- **citation_text**: Marker in text (`"[1]"`, `"(Smith, 2020)"`)
- **citation_details**: Full parsed citation info (title, authors, year, DOI, URL)

**Special Fields:**
- **is_original**: `true` = paper's own contribution (from experiments/results); `false` = cites external sources

**Citation ID Format:**
- Numeric: `[1]` → `"1"`, `[23]` → `"23"`
- Author-year: `(Smith, 2020)` → `"Smith"`, `(Jones et al., 2019)` → `"Jones"`

### Claim Ordering (Sorting & Grouping)

For efficient downstream validation, the list of claim objects is partioned into 4 sections based on type, in the following order:

1. **Qualitative WITHOUT citations** → Fast verification (truth table/LLM)
2. **Quantitative WITHOUT citations** → Need source finding
3. **Qualitative WITH citations** → Batch text download + RAG
4. **Quantitative WITH citations** → Batch dataset download + scripts

Additionally, within the section for each type, claims with the same `citation_id` are grouped together for batch processing, 
but only for claims with found citation(s) (e.g. the last two sections).

### Sample JSON Structure Example
```json
{
  "claims": [
    {
      "claim_id": "claim_0_1",
      "text": "The model achieved 95% accuracy on the test set.",
      "claim_type": "quantitative",
      "citation_found": false,
      "citation_id": null,
      "citation_text": null,
      "citation_details": null,
      "is_original": true,
      "location_in_text": {
        "start": 1234,
        "end": 1289,
        "chunk_id": 0
      }
    },
    {
      "claim_id": "claim_1_2",
      "text": "Prior work showed neural networks improve performance.",
      "claim_type": "qualitative",
      "citation_found": true,
      "citation_id": "5",
      "citation_text": "[5]",
      "citation_details": {
        "title": "Neural Networks in NLP",
        "authors": ["Smith, J.", "Doe, A."],
        "year": 2023,
        "url": "https://example.com/paper",
        "doi": "10.1234/example",
        "raw_text": "Smith, J. & Doe, A. (2023). Neural Networks..."
      },
      "is_original": false,
      "location_in_text": {
        "start": 3456,
        "end": 3512,
        "chunk_id": 1
      }
    }
  ],
  "citations": {
    "5": "Smith, J. & Doe, A. (2023). Neural Networks in NLP. ACL 2023."
  },
  "summary": {
    "total_claims": 15,
    "quantitative_claims": 8,
    "qualitative_claims": 7,
    "claims_with_citations": 12,
    "original_contributions": 3
  }
}
```

## Workflow

### Pipeline (4 Stages)

#### 1. Citation Extraction (Hybrid)
- Load PDF text with LangChain PyPDFLoader
- Locate reference section (70% heuristic)
- **Try:** Deterministic regex parsing first (APA, MLA, numeric, author-year formats)
- **Fallback:** GPT-4o-mini if regex fails

#### 2. Text Chunking (Sentence-Boundary)
- Remove reference section from body
- Split on sentence boundaries (`.`, `!`, `?`)
- Create ~800 token chunks
- Add 100-char overlap to prevent splitting claims

#### 3. Claim Extraction (LLM with Smart Filtering)
- Extract paper title and abstract for context
- Send each chunk to GPT-4o-mini
- LLM identifies:
  - All objective, fact-based claims (quantitative and qualitative)
  - Citation markers in text
  - Whether claim is original contribution
- **Filters out:** 
  - Common knowledge (e.g., "water boils at 100°C")
  - Subjective opinions and interpretations (e.g., "This approach is promising")
- **Includes:** Objective research findings, verifiable assertions

#### 4. Citation Mapping & Efficient Sorting
- Match citation markers to parsed citations (deterministic)
- Populate full citation details
- Sort claims by type and citation status
- Groups claims by citation for batch processing
- Prioritizes fast-to-validate claims first
- Monitors OpenAI API token usage and costs in real-time
- Return structured results


## Configuration

Edit `config.py` to customize:

```python
# LLM settings
CLAIM_EXTRACTION_MODEL = "gpt-4o-mini"
CLAIM_EXTRACTION_TEMPERATURE = 0.2
ENABLE_COST_TRACKING = True

# Chunking
CHUNK_SIZE = 800                      # Tokens per chunk
CHUNK_OVERLAP = 100                   # Character overlap between chunks

# Reference section
REFERENCE_SECTION_THRESHOLD = 0.7     # Start searching at 70% through doc
```

## Integration with Validation Pipeline

This module is **Stage 1** of the complete ASV pipeline:

```
Stage 1: hybrid_citation_scraper (this module)
    ↓ List[ClaimObject]
Stage 2: validator (orchestrates validation)
    ↓ Uses utilities
Stage 3: sourcefinder_tools (finds/downloads sources)
    ↓
Results: JSON files with validation outcomes
```

To run the complete pipeline:
```python
from hybrid_citation_scraper import HybridClaimExtractor
from validator import ClaimValidator

# Extract claims
extractor = HybridClaimExtractor()
claims = extractor.process_pdf("paper.pdf")

# Validate claims (see validator module)
validator = ClaimValidator()
results = validator.process_claims(claims)
```

See [main README](../README.md) for complete pipeline documentation.

## Module Files

- `claim_extractor.py` - Main extraction pipeline
- `llm_client.py` - OpenAI API wrapper
- `utils.py` - Text processing utilities
- `config.py` - Configuration settings
- `__init__.py` - Module exports

## Data Models

All models defined in [`../models.py`](../models.py):
- `ClaimObject` - Individual claim with metadata
- `CitationDetails` - Parsed citation information
- `LocationInText` - Character positions in PDF

## Cost Information

**GPT-4o-mini Pricing:**
- Input: $0.150 per 1M tokens
- Output: $0.600 per 1M tokens

**Per Paper:**
- 10-page paper: ~$0.002-0.003
- 20-page paper: ~$0.004-0.006

**Bulk Processing:**
- 100 papers: ~$0.20-0.30
- 1,000 papers: ~$2.00-3.00

**Tracking Usage:**
```python
# Check costs after processing
cost_info = extractor.llm_client.get_cost_summary()
print(f"Input tokens: {cost_info['input_tokens']:,}")
print(f"Output tokens: {cost_info['output_tokens']:,}")
print(f"Total cost: ${cost_info['total_cost']:.4f}")
```

## Troubleshooting

**"No API key found"**
- Set environment variable: `OPENAI_API_KEY=sk-...`

**"No claims extracted"**
- Check PDF is text-based (not scanned image)
- Try adjusting `CHUNK_SIZE` in config

**"High API costs"**
- Enable `ENABLE_COST_TRACKING` to monitor usage
- Use smaller chunk sizes for shorter papers

**"Missing citations"**
- Check reference section is detected (70% threshold)
- Try adjusting `REFERENCE_SECTION_THRESHOLD`

## Limitations

1. **PDF Format**: Works best with text-based PDFs (not scanned images)
2. **Citation Formats**: Optimized for academic papers (APA, MLA, numeric)
3. **Language**: English only (LLM prompt in English)
4. **Common Knowledge**: Filters out basic facts automatically

## Next Steps

After extraction, claims are ready for validation:
- See [`../validator/`](../validator/) for claim validation
- See [`../sourcefinder_tools/`](../sourcefinder_tools/) for source finding
- See [`../README.md`](../README.md) for complete pipeline
