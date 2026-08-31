"""API-launched pipeline runner.

Same job as scripts/run_pipeline.py, with two differences required for
running as a subprocess spawned by the FastAPI backend rather than from a
terminal:

  1. Reattaches to a run folder the backend's job_manager already created
     (via RunPaths.from_existing) instead of creating its own — the API needs
     to know run_id at launch time, before this process has even started.
  2. Wires a FileInteractionHandler so a paywall-login checkpoint polls
     control/login_ack.json instead of blocking on stdin, which does not
     exist for a subprocess with no attached terminal (C2 / B6).

Not meant for direct CLI use — invoked by api/services/job_manager.py.
Usage:
    python scripts/run_pipeline_api.py <pdf_path> <run_dir>
"""

import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_ROOT))

from asv.extraction.claim_extractor import HybridClaimExtractor
from asv.orchestrator import ClaimOrchestrator
from asv.core.run_paths import RunPaths
from asv.core.run_events import RunEventLogger
from asv.core.interaction import FileInteractionHandler


def main():
    if len(sys.argv) < 3:
        print("Usage: python scripts/run_pipeline_api.py <pdf_path> <run_dir>")
        sys.exit(1)

    pdf_path = sys.argv[1]
    run_dir = sys.argv[2]

    if not Path(pdf_path).exists():
        print(f"Error: PDF not found: {pdf_path}")
        sys.exit(1)

    run_paths = RunPaths.from_existing(run_dir)
    print(f"[ASV] Run folder: {run_paths.root}")

    extractor = HybridClaimExtractor()
    claims, citations = extractor.process_pdf(pdf_path)
    claims_json_path = extractor.save_results(pdf_path=pdf_path, run_paths=run_paths)
    print(f"[ASV] Claims written to: {claims_json_path}")

    events = RunEventLogger(run_paths)
    interaction = FileInteractionHandler(run_paths, events)
    orchestrator = ClaimOrchestrator(run_paths=run_paths, interaction=interaction)
    results = orchestrator.process_claims(claims, citations)

    total = sum(len(v) for v in results.values())
    print(f"\n[ASV] Done. {total} result entries.")
    print(f"[ASV] Run folder: {run_paths.root}")


if __name__ == "__main__":
    main()
