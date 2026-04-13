"""
Run the ClaimOrchestrator on a pre-extracted claims JSON file.

Usage:
    python scripts/run_orchestrator.py <path/to/claims.json>
    python scripts/run_orchestrator.py hybrid_citation_scraper/test_outputs/hsv_cancer_claims.json
"""

import sys
from pathlib import Path

# Ensure project root is on the path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orchestrator import ClaimOrchestrator


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/run_orchestrator.py <claims_json_path>")
        sys.exit(1)

    json_path = sys.argv[1]
    if not Path(json_path).exists():
        print(f"Error: file not found: {json_path}")
        sys.exit(1)

    orchestrator = ClaimOrchestrator()
    claims, citations = ClaimOrchestrator.load_claims_from_json(json_path)
    results = orchestrator.process_claims(claims, citations)

    total = sum(
        len(v) for v in results.values()
    )
    print(f"\nDone. {total} result entries written to {orchestrator.output_dir}/")
    print(f"Log: {orchestrator._log_path}")


if __name__ == "__main__":
    main()
