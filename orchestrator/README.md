# Orchestrator Module

Orchestration logic for claim validation lives here.

## Responsibilities

- Route claims through the fixed validation order
- Batch cited claims by `citation_id`
- Coordinate `sourcefinder_tools` downloads
- Invoke validator tools (`TruthTableChecker`, `LLMVerifier`) and orchestration sub-validators
- Persist grouped output JSON files

## Modules

- `claim_orchestrator.py` - Main pipeline orchestration (`ClaimOrchestrator`)
- `process_quantitative.py` - Quantitative claim processing orchestration
- `process_qualitative.py` - Qualitative claim processing orchestration
- `__init__.py` - Exports orchestration classes

## Usage

```python
from orchestrator import ClaimValidator

validator = ClaimValidator(output_dir="validation_results")
results = validator.process_claims(claims)
```
