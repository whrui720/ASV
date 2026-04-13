"""
Test 2 of 3 — PythonScriptValidator

Downloads a well-known public CSV (Iris dataset), then asks the validator to:
  - Verify a TRUE claim  (mean sepal length ≈ 5.84 cm)
  - Verify a FALSE claim (five species instead of three)

The validator generates a Python script via the LLM, executes it, and returns a
structured result. Generated scripts are saved to ./generated_scripts/.

Run from the repo root:
  python scripts/test_python_script_validator.py
"""

import sys
import logging
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")
logger = logging.getLogger("test_script_validator")

# Stable public CSV — Iris dataset, 150 rows, always accessible
DATASET_URL = (
    "https://raw.githubusercontent.com/mwaskom/seaborn-data/master/iris.csv"
)
CITATION_ID = "test_iris_001"

CLAIMS = [
    {
        "id": "test_iris_true",
        "label": "TRUE claim",
        "text": (
            "The average sepal length across all iris species in the dataset "
            "is approximately 5.84 cm."
        ),
    },
    {
        "id": "test_iris_false",
        "label": "FALSE claim",
        "text": (
            "The dataset contains records from five distinct iris species."
        ),
    },
]


def download_dataset():
    """Download Iris CSV; return local path."""
    from sourcefinder.dataset_downloader import DatasetDownloader

    logger.info("─" * 50)
    logger.info("SETUP  Downloading Iris CSV for validation tests")
    downloader = DatasetDownloader()
    result = downloader.download(DATASET_URL, CITATION_ID)

    if not result["downloaded"]:
        print(f"[FAIL] Could not download dataset: {result.get('error')}")
        sys.exit(1)

    logger.info(f"  saved to: {result['path']}")
    return result["path"], downloader


def main():
    from hybrid_citation_scraper.llm_client import LLMClient
    from validator.python_script_validator import PythonScriptValidator

    print("\n" + "=" * 60)
    print(" TEST: PythonScriptValidator")
    print("=" * 60)

    dataset_path, downloader = download_dataset()
    # Resolve to absolute so generated scripts can find the file regardless of cwd
    dataset_path = str(Path(dataset_path).resolve())

    llm = LLMClient()
    validator = PythonScriptValidator(llm_client=llm)

    results = []
    for claim in CLAIMS:
        print(f"\n{'-' * 50}")
        print(f"[{claim['label']}]")
        print(f"  Claim: {claim['text']}")

        logger.info("─" * 50)
        logger.info(f"Validating [{claim['label']}]: {claim['id']}")

        result = validator.validate(
            claim_text=claim["text"],
            dataset_path=dataset_path,
            claim_id=claim["id"],
        )

        verdict = "PASS" if result.get("passed") else "FAIL"
        print(f"  validated   : {result.get('validated')}")
        print(f"  verdict     : {verdict}")
        print(f"  confidence  : {result.get('confidence', 0.0):.2f}")
        print(f"  explanation : {result.get('explanation', '')}")
        if result.get("error"):
            print(f"  error       : {result['error']}")

        script_path = Path("generated_scripts") / f"validate_{claim['id']}.py"
        if script_path.exists():
            print(f"  script      : {script_path}")

        results.append((claim["label"], result))

    # ── Cleanup ───────────────────────────────────────────────────────────────
    logger.info("─" * 50)
    logger.info("CLEANUP  Deleting downloaded dataset")
    filename = Path(dataset_path).name
    downloader.delete_dataset(filename)

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print(" SUMMARY")
    print("=" * 60)
    hard_errors = []
    for label, res in results:
        verdict = "PASS" if res.get("passed") else "FAIL"
        conf = res.get("confidence", 0.0)
        print(f"  [{label}]  {verdict}  conf={conf:.2f}  — {res.get('explanation', '')}")
        if not res.get("validated") and res.get("error"):
            hard_errors.append(label)

    if hard_errors:
        print(f"\n[FAIL] Hard execution errors in: {hard_errors}")
        sys.exit(1)
    else:
        print("\n[OK] Validator ran without hard errors.")

    print()


if __name__ == "__main__":
    main()
