"""
Re-run validation for a single citation's claims within an existing run —
used by the web backend's "retry" action (S3/S6) after a human fixes a
source (supplies a URL, completes a paywall login) so the whole pipeline
doesn't have to re-run for one bad citation. See ClaimOrchestrator.revalidate_citation
(B5, docs/FRONTEND_PLAN.md §9).

Usage:
    python scripts/revalidate_citation.py <run_dir> <citation_id> [override_url]
"""

import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orchestrator import ClaimOrchestrator
from run_paths import RunPaths


def main():
    if len(sys.argv) < 3:
        print("Usage: python scripts/revalidate_citation.py <run_dir> <citation_id> [override_url]")
        sys.exit(1)

    run_dir = sys.argv[1]
    citation_id = sys.argv[2]
    override_url = sys.argv[3] if len(sys.argv) >= 4 else None

    run_paths = RunPaths.from_existing(run_dir)
    claims_json_path = run_paths.claims_json()
    if not claims_json_path.exists():
        print(f"Error: claims JSON not found at {claims_json_path}")
        sys.exit(1)

    orchestrator = ClaimOrchestrator(run_paths=run_paths)
    try:
        batch = orchestrator.revalidate_citation(citation_id, str(claims_json_path), override_url)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    if batch is None:
        print(f"[ASV] No batch produced for citation [{citation_id}]")
        sys.exit(1)

    print(
        f"[ASV] Retried citation [{citation_id}]: "
        f"download_successful={batch.download_successful}, "
        f"{len(batch.claim_results)} claim(s) revalidated"
    )


if __name__ == "__main__":
    main()
