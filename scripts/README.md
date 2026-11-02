# Scripts

Project entry points and utility scripts.

Every script bootstraps `sys.path` with `src/` (for the `asv` package) and the repo
root (for `apps`), so they run without an editable install — though `pip install -e .`
is recommended.

## Pipeline entry points

- `run_pipeline.py`: **Canonical end-to-end runner.** Takes a PDF, creates a fresh `runs/{pdf_stem}__{YYYYMMDD_HHMMSS}/` folder, runs claim extraction, then orchestrates validation. Every artifact is written under the run folder.
- `run_orchestrator.py`: Reruns orchestration against a pre-extracted claims JSON. Auto-detects the run folder if the JSON sits inside one (`runs/{stem}__{ts}/citations/`); otherwise synthesizes a fresh run folder. Accepts an optional explicit `run_dir` second argument.
- `run_pipeline_api.py`: The subprocess entry point the web API (`apps/api`) shells out to per run — same pipeline as `run_pipeline.py` but driven by the API's job manager (file-based interaction handler for paywall login, `events.jsonl` progress). Not usually run by hand.
- `revalidate_citation.py`: Re-runs validation for a single citation batch within an existing run (used by the API's "retry source" action).

## Web app

- `run_webapp.py`: Builds the frontend (`apps/web`) if needed, then starts the FastAPI backend (`apps/api`, served at `apps.api.main:app`) which also serves the built bundle. `--no-build`, `--port`, `--reload` flags available.

## Auditing and benchmarking

Run by hand; these are the only scripts besides the pipeline that touch the network.
`docs/TIER0_PLAN.md` §7 explains which parts are code and which are irreducibly manual.

- `probe_existence_apis.py`: checks that the free bibliographic indexes (Crossref, OpenAlex, Europe PMC, PubMed, DataCite) still answer with the fields `index_clients.py` reads.
- `calibrate_content_quality.py`: re-fetches past sources and writes a CSV to hand-label; `--score` scores the content-quality classifier against those labels.
- `build_gold_seed.py`: seeds gold-set claim/source pairs from existing runs into `benchmarks/gold/`.
- `seed_miscitations.py`: proposes hard negatives (corrupted claim/source pairs); a human accepts each one.
- `eval_gold.py`: computes precision, recall and false-accusation rate over the labelled gold set (`--repeats N` for determinism).

Pairs are labelled in the web UI at `/benchmark`.

## Test runners

- `run_tests.py`: Python test runner wrapper around pytest.
- `run_tests.ps1`: PowerShell test runner for Windows.

## Standalone module tests

- `test_dataset_finder_downloader.py`: Smoke-test the dataset finder + downloader path without invoking the full orchestrator.
- `test_python_script_validator.py`: Smoke-test the Python script generation/execution validator.

These two are manual smoke scripts, not pytest modules; `pytest.ini` only collects from the package test directories.

## Usage

From repository root:

```powershell
# End-to-end pipeline
python scripts/run_pipeline.py pdfs/<paper>.pdf

# Re-run orchestration only
python scripts/run_orchestrator.py runs/<stem>__<ts>/citations/<stem>_claims.json

# Tests
python scripts/run_tests.py --coverage --html-report
.\scripts\run_tests.ps1 -Coverage -HtmlReport
```

All scripts resolve paths against the repository root.
