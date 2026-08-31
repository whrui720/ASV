"""End-to-end ASV pipeline runner.

Takes a PDF, creates a fresh run folder at runs/{pdf_stem}__{timestamp}/,
runs claim extraction, then orchestrates validation — every artifact is
written under the run folder.

Usage:
    python scripts/run_pipeline.py <path/to/paper.pdf>
"""

import sys
from pathlib import Path

# Make stdout/stderr UTF-8 so unicode log prints (✓, ✗, →, etc.) don't crash on Windows cp1252.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Ensure the package roots are importable: src/ for `asv`, repo root for `apps`.
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_ROOT))

from asv.extraction.claim_extractor import HybridClaimExtractor
from asv.orchestrator import ClaimOrchestrator
from asv.core.run_paths import RunPaths


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/run_pipeline.py <pdf_path>")
        sys.exit(1)

    pdf_path = sys.argv[1]
    if not Path(pdf_path).exists():
        print(f"Error: PDF not found: {pdf_path}")
        sys.exit(1)

    run_paths = RunPaths.for_pdf(pdf_path)
    print(f"[ASV] Run folder: {run_paths.root}")

    extractor = HybridClaimExtractor()
    claims, citations = extractor.process_pdf(pdf_path)
    claims_json_path = extractor.save_results(pdf_path=pdf_path, run_paths=run_paths)
    print(f"[ASV] Claims written to: {claims_json_path}")

    orchestrator = ClaimOrchestrator(run_paths=run_paths)
    results = orchestrator.process_claims(claims, citations)

    total = sum(len(v) for v in results.values())
    print(f"\n[ASV] Done. {total} result entries.")
    print(f"[ASV] Run folder: {run_paths.root}")
    print(f"[ASV] Validation results: {run_paths.validation_results}")
    print(f"[ASV] Summary: {run_paths.run_summary_json()}")
    print(f"[ASV] Log: {run_paths.orchestration_log()}")


if __name__ == "__main__":
    main()
