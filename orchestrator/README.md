# Orchestrator Module

Orchestration logic for claim validation lives here.

## Responsibilities

- Route claims through the fixed validation order
- Batch cited claims by `citation_id`
- Coordinate `sourcefinder` downloads
- Invoke validator tools (`TruthTableChecker`, `LLMVerifier`) and orchestration sub-validators
- Persist grouped output JSON files under the active run folder

## Modules

- `claim_orchestrator.py` - Main pipeline orchestration (`ClaimOrchestrator`)
- `process_quantitative.py` - Quantitative claim processing orchestration
- `process_qualitative.py` - Qualitative claim processing orchestration
- `__init__.py` - Exports orchestration classes

## Usage

The orchestrator requires a `RunPaths` object (defined in `run_paths.py` at the project root). It owns every on-disk artifact for a single PDF — claims JSON, downloaded sources, generated scripts, validation results, summary, log.

```python
from orchestrator import ClaimOrchestrator
from run_paths import RunPaths

run_paths = RunPaths.for_pdf("pdfs/paper.pdf")
orchestrator = ClaimOrchestrator(run_paths=run_paths)
results = orchestrator.process_claims(claims, citations)

# All outputs live under run_paths.root:
# - run_paths.validation_results / *.json      (4 result files)
# - run_paths.run_summary_json()               (final_output/run_summary.json)
# - run_paths.orchestration_log()              (logs/orchestration.log)
# - run_paths.found_datasets_json()            (sourcefinder/found_datasets.json)
# - run_paths.found_text_sources_json()        (sourcefinder/found_text_sources.json)
```
