# Scripts

Project entry points and utility scripts.

## Pipeline entry points

- `run_pipeline.py`: **Canonical end-to-end runner.** Takes a PDF, creates a fresh `runs/{pdf_stem}__{YYYYMMDD_HHMMSS}/` folder, runs claim extraction, then orchestrates validation. Every artifact is written under the run folder.
- `run_orchestrator.py`: Reruns orchestration against a pre-extracted claims JSON. Auto-detects the run folder if the JSON sits inside one (`runs/{stem}__{ts}/citations/`); otherwise synthesizes a fresh run folder. Accepts an optional explicit `run_dir` second argument.

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
