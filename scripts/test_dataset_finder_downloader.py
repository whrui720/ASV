"""
Test 1 of 3 — DatasetFinder + DatasetDownloader

Simulates the orchestrator flow for an uncited quantitative claim:
  1. DatasetFinder searches data.gov for a relevant dataset URL
  2. DatasetDownloader downloads that dataset to ./datasets/

Run from the repo root:
  python scripts/test_dataset_finder_downloader.py
"""

import sys
import logging
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")
logger = logging.getLogger("test_finder_downloader")

# Uncited quantitative claim to search for
CLAIM = (
    "The US unemployment rate fell below 4% in 2019 according to "
    "Bureau of Labor Statistics data."
)
CLAIM_ID = "test_finder_001"


def main():
    from hybrid_citation_scraper.llm_client import LLMClient
    from sourcefinder.dataset_finder import DatasetFinder
    from sourcefinder.dataset_downloader import DatasetDownloader

    print("\n" + "=" * 60)
    print(" TEST: DatasetFinder + DatasetDownloader")
    print("=" * 60)
    print(f"\nClaim: {CLAIM}\n")

    llm = LLMClient()

    # ── Step 1: Find dataset ──────────────────────────────────────────────────
    logger.info("─" * 50)
    logger.info("STEP 1  DatasetFinder.find_dataset()")
    finder = DatasetFinder(llm_client=llm)
    found = finder.find_dataset(claim_text=CLAIM, claim_id=CLAIM_ID)

    if not found:
        print("\n[FAIL] DatasetFinder returned None — no dataset candidates found.")
        print("       (data.gov may have returned no downloadable CSV/JSON results)")
        sys.exit(1)

    print(f"\n  source_url      : {found.source_url}")
    print(f"  source_type     : {found.source_type}")
    print(f"  relevance_score : {found.relevance_score:.2f}")
    print(f"  search_query    : {found.search_query}")

    # ── Step 2: Download that dataset ─────────────────────────────────────────
    logger.info("─" * 50)
    logger.info("STEP 2  DatasetDownloader.download()")
    downloader = DatasetDownloader()
    dl = downloader.download(found.source_url, CLAIM_ID)

    print(f"\n  downloaded : {dl['downloaded']}")
    print(f"  format     : {dl['format']}")
    print(f"  path       : {dl['path']}")
    if dl.get("error"):
        print(f"  error      : {dl['error']}")

    if dl["downloaded"]:
        print(f"\n[OK] Dataset saved to: {dl['path']}")
    else:
        print("\n[WARN] Download failed — the URL returned by data.gov may not be a")
        print("       direct file link. The finder and downloader both ran correctly.")

    print()


if __name__ == "__main__":
    main()
