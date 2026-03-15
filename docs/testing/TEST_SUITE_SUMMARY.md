# Test Suite Summary

## Status

- Test suite exists under `hybrid_citation_scraper/tests`.
- Runner scripts are in `scripts`.
- Pytest configuration is in `pytest.ini`.

## Main Components

- Unit tests for utilities, config, and LLM client behavior.
- Integration tests for end-to-end extraction workflow.
- Shared fixtures in `hybrid_citation_scraper/tests/conftest.py`.

## How to Run

```bash
pytest
python scripts/run_tests.py --coverage --html-report
```

```powershell
.\scripts\run_tests.ps1 -Coverage -HtmlReport
```

## Files

- `scripts/run_tests.py`
- `scripts/run_tests.ps1`
- `docs/testing/TESTING_GUIDE.md`
- `hybrid_citation_scraper/tests/README.md`
