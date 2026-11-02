# Testing

The suite uses **pytest** and runs entirely offline. `pytest.ini` holds the discovery
config, markers and coverage settings.

## Where the tests are

| Directory | Covers |
|---|---|
| `src/asv/extraction/tests/` | claim extraction, citation parsing, LLM client |
| `src/asv/validator/tests/` | RAG verification, quote verification |
| `src/asv/sourcefinder/tests/` | resolvers, downloaders, content-quality gate, bibliography audit, and every external API client (`test_api_*.py`) |
| `src/asv/orchestrator/tests/` | routing, abstention paths, pipeline smoke test |
| `apps/api/tests/` | FastAPI read model and routers |
| `src/asv/core/tests/` | credentials catalogue. **Not in `pytest.ini`'s `testpaths`**, so a bare `pytest` skips it; run `pytest src/asv/core/tests` |

## Install

```bash
pip install -e ".[dev]"    # asv package + all test/dev tooling
```

## Run

```bash
pytest                     # everything in testpaths
pytest -m unit             # unit only
pytest -m integration      # integration only
pytest -m "not slow"       # skip slow
pytest --cov=asv --cov-report=term-missing --cov-report=html
pytest src/asv/sourcefinder/tests/test_api_index_clients.py   # one file
```

Script wrappers: `python scripts/run_tests.py --coverage --html-report`, or
`.\scripts\run_tests.ps1 -Coverage -HtmlReport` on Windows.

## External APIs

The `test_api_*.py` modules in `src/asv/sourcefinder/tests/` replace `PoliteSession` with
`FakeHttp` (`tests/api_fakes.py`) and replay real responses captured under
`tests/fixtures/api/`. The package `conftest.py` fails any test that reaches the network
or reads a real `.env` credential; set a credential with the `creds` fixture.

`test_api_contracts_live.py` runs the same clients against the real services, to catch a
response shape changing. It is opt-in:

```bash
ASV_LIVE_API_TESTS=1 pytest -m live --no-cov    # ~1 min; a 429 or timeout reports as skipped
```

## Markers

`unit`, `integration`, `slow`, `requires_api`, `live`. `--strict-markers` is on, so a new
marker has to be declared in `pytest.ini` first.

## Notes

- LLM calls are stubbed. Nothing in the default suite needs a Gemini key.
- Coverage artifacts land in `htmlcov/` and `coverage.xml` (both gitignored).
- A repo-root `conftest.py` puts `src/` and the repo root on `sys.path`, so `import asv`
  and `import apps.api` resolve without an editable install. Run from the repo root.
