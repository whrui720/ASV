# Orchestrator Module

Orchestration logic for claim validation lives here.

## Responsibilities

- Route claims through the fixed validation order
- Batch cited claims by `citation_id`
- Split cited-quantitative batches by source shape (dataset-backed vs paper-backed) — see below
- Coordinate `sourcefinder` downloads
- Invoke validator tools (`TruthTableChecker`, `LLMVerifier`) and orchestration sub-validators
- Persist grouped output JSON files under the active run folder

## Modules

- `claim_orchestrator.py` - Main pipeline orchestration (`ClaimOrchestrator`)
- `process_quantitative.py` - Quantitative claim processing (dataset-backed script validation path)
- `process_qualitative.py` - Qualitative claim processing (RAG + LLM verification path; also used for paper-backed cited-quantitative claims)
- `__init__.py` - Exports orchestration classes

## Cited-quantitative routing split

`_process_cited_quantitative` partitions its input by `claim.found_source`:

| Predicate | Path | Method |
|---|---|---|
| `found_source is not None` (dataset resolver returned a real tabular URL) | `_process_dataset_backed_quant` | `DatasetDownloader → PythonScriptValidator` — download tabular data, generate + execute Python script, parse JSON verdict. `validation_method="python_script"`. |
| `found_source is None` (citation is an academic paper) | `_process_paper_backed_quant` | `TextDownloader.download_with_resolution → ProcessQualitative.validate_claim` — download paper text (PDF/HTML), retrieve top-K chunks via TF-IDF, LLM verifies claim against chunks. `validation_method="rag_search"`, `claim_type` stays `"quantitative"`. |

`found_source` is populated only by `_process_uncited_quantitative` when `DatasetFinder` locates a genuine dataset (data.gov / Kaggle / Zenodo / etc.). Every other cited-quantitative claim inherits `found_source = None` and lands in the paper-backed branch.

Both branches emit `ValidationBatch` objects into the same `quantitative_cited_results.json` output. Downstream consumers don't need to know which branch produced a batch — the `source_path` extension (`.csv`/`.json`/`.xlsx` vs `.pdf`/`.html`) tells you if needed, but the schema is identical.

The paper-backed branch appends its resolution attempts to `text_source_manifest` (not `dataset_manifest`), matching where its downloads live.

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
