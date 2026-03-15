# Scripts

Project utility scripts.

## Available Scripts

- `run_tests.py`: Python test runner wrapper around pytest.
- `run_tests.ps1`: PowerShell test runner for Windows.

## Usage

From repository root:

```powershell
python scripts/run_tests.py --coverage --html-report
.\scripts\run_tests.ps1 -Coverage -HtmlReport
```

Both scripts resolve paths against the repository root.
