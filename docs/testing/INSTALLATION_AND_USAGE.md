# Installation And Usage (Testing)

This page focuses on installing test dependencies and running the test suite.

## Install

```bash
pip install -r requirements.txt
pip install -r hybrid_citation_scraper/tests/test_requirements.txt
```

## Run Tests

```bash
pytest
```

### With Coverage

```bash
pytest --cov=hybrid_citation_scraper --cov-report=term-missing --cov-report=html
```

### Script Wrappers

```bash
python scripts/run_tests.py --coverage --html-report
```

```powershell
.\scripts\run_tests.ps1 -Coverage -HtmlReport
```

## Troubleshooting

- Import issues: run tests from repository root.
- Missing packages: reinstall test requirements.
- Coverage report: open `htmlcov/index.html`.

## Related Docs

- `docs/testing/TESTING_GUIDE.md`
- `docs/testing/TEST_SUITE_SUMMARY.md`
- `hybrid_citation_scraper/tests/README.md`
