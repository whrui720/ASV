# Testing

The suite uses **pytest**. Tests live in `src/asv/extraction/tests/` and `apps/api/tests/`
(see `pytest.ini` for discovery config and markers).

## Install

```bash
pip install -e ".[dev]"    # asv package + all test/dev tooling (canonical)
# or, without the editable package:
pip install -r requirements.txt
pip install -r src/asv/extraction/tests/test_requirements.txt
```

## Run

```bash
pytest                     # everything
pytest -m unit             # unit only
pytest -m integration      # integration only
pytest -m "not slow"       # skip slow
pytest --cov=asv --cov-report=term-missing --cov-report=html
```

Script wrappers:

```bash
python scripts/run_tests.py --coverage --html-report
```
```powershell
.\scripts\run_tests.ps1 -Coverage -HtmlReport
```

Run a single file or test:

```bash
pytest src/asv/extraction/tests/test_utils.py
pytest src/asv/extraction/tests/test_claim_extractor.py::TestProcessPDF
```

## Layout & markers

- Unit tests: utilities, config, LLM client behavior.
- Integration tests: end-to-end extraction workflow.
- Shared fixtures: `src/asv/extraction/tests/conftest.py`, `apps/api/tests/conftest.py`.
  A repo-root `conftest.py` puts `src/` and the repo root on `sys.path` so `import asv`
  and `import apps.api` resolve even without an editable install.
- Markers: `unit`, `integration`, `slow`, `requires_api`.

## Notes

- LLM/API calls are mocked in most tests.
- Coverage artifacts land in `htmlcov/` and `coverage.xml` (both gitignored).
- Import errors usually mean you're not running from the repo root — `cd` to the root first.

See also: `src/asv/extraction/tests/README.md` for test-source specifics.
