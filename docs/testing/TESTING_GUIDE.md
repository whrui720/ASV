# Testing Guide

This project uses pytest with tests located in `hybrid_citation_scraper/tests`.

## Quick Start

1. Install dependencies:

```bash
pip install -r requirements.txt
pip install -r hybrid_citation_scraper/tests/test_requirements.txt
```

2. Run tests:

```bash
pytest
```

3. Run with coverage:

```bash
pytest --cov=hybrid_citation_scraper --cov-report=term-missing --cov-report=html
```

4. Use script wrappers:

```bash
python scripts/run_tests.py --coverage --html-report
```

```powershell
.\scripts\run_tests.ps1 -Coverage -HtmlReport
```

## Useful Commands

```bash
pytest -v
pytest -m unit
pytest -m integration
pytest -m "not slow"
pytest hybrid_citation_scraper/tests/test_utils.py
pytest hybrid_citation_scraper/tests/test_claim_extractor.py::TestProcessPDF
```

## Test Layout

- `hybrid_citation_scraper/tests/test_utils.py`
- `hybrid_citation_scraper/tests/test_llm_client.py`
- `hybrid_citation_scraper/tests/test_claim_extractor.py`
- `hybrid_citation_scraper/tests/test_config.py`
- `hybrid_citation_scraper/tests/test_integration.py`
- `hybrid_citation_scraper/tests/conftest.py`

## Notes

- API calls are mocked in most tests.
- Coverage artifacts are generated under `htmlcov` and `coverage.xml`.
- Markers available: `unit`, `integration`, `slow`, `requires_api`.
