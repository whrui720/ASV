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

## Test runners

- `run_tests.py`: Python test runner wrapper around pytest.
- `run_tests.ps1`: PowerShell test runner for Windows.

## Standalone module tests

- `test_dataset_finder_downloader.py`: Smoke-test the dataset finder + downloader path without invoking the full orchestrator.
- `test_python_script_validator.py`: Smoke-test the Python script generation/execution validator.

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
