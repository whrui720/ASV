# Testing

The suite uses **pytest**. Tests live in `hybrid_citation_scraper/tests/` and `api/tests/`
(see `pytest.ini` for discovery config and markers).

## Install

```bash
pip install -r requirements.txt
pip install -r hybrid_citation_scraper/tests/test_requirements.txt
# or, once packaged (see docs/RESTRUCTURE.md): pip install -e .[dev]
```

## Run

```bash
pytest                     # everything
pytest -m unit             # unit only
pytest -m integration      # integration only
pytest -m "not slow"       # skip slow
pytest --cov=hybrid_citation_scraper --cov-report=term-missing --cov-report=html
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
pytest hybrid_citation_scraper/tests/test_utils.py
pytest hybrid_citation_scraper/tests/test_claim_extractor.py::TestProcessPDF
```

## Layout & markers

- Unit tests: utilities, config, LLM client behavior.
- Integration tests: end-to-end extraction workflow.
- Shared fixtures: `hybrid_citation_scraper/tests/conftest.py`, `api/tests/conftest.py`.
- Markers: `unit`, `integration`, `slow`, `requires_api`.

## Notes

- LLM/API calls are mocked in most tests.
- Coverage artifacts land in `htmlcov/` and `coverage.xml` (both gitignored).
- Import errors usually mean you're not running from the repo root — `cd` to the root first.

See also: `hybrid_citation_scraper/tests/README.md` for test-source specifics.
