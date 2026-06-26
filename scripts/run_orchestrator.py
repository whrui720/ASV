"""
Run the ClaimOrchestrator on a pre-extracted claims JSON file.

Usage:
    python scripts/run_orchestrator.py <claims_json_path> [run_dir]

Run-folder resolution (in order of precedence):
  1. ``run_dir`` argument (if given) — reattach via RunPaths.from_existing.
  2. The claims JSON already lives inside runs/{stem}__{ts}/citations/ —
     walk up two parents and reattach.
  3. Otherwise (legacy claims JSON, e.g. under hybrid_citation_scraper/test_outputs/) —
     synthesize a fresh run folder via RunPaths.for_pdf.
"""

import sys
from pathlib import Path

# Make stdout/stderr UTF-8 so unicode log prints (✓, ✗, →, etc.) don't crash on Windows cp1252.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Ensure project root is on the path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orchestrator import ClaimOrchestrator
from run_paths import RunPaths


def _resolve_run_paths(claims_json: Path, explicit_run_dir: str | None) -> RunPaths:
    if explicit_run_dir:
        return RunPaths.from_existing(explicit_run_dir)

    # Detect: claims_json under runs/<stem>__<ts>/citations/<stem>_claims.json
    parent = claims_json.parent
    grandparent = parent.parent
    if parent.name == "citations" and "__" in grandparent.name:
        return RunPaths.from_existing(grandparent)

    # Legacy fallback: synthesize a fresh run keyed off the claims-JSON stem.
    pdf_stem = claims_json.stem
    if pdf_stem.endswith("_claims"):
        pdf_stem = pdf_stem[: -len("_claims")]
    return RunPaths.for_pdf(pdf_stem)


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/run_orchestrator.py <claims_json_path> [run_dir]")
        sys.exit(1)

    json_path = Path(sys.argv[1])
    explicit_run_dir = sys.argv[2] if len(sys.argv) >= 3 else None

    if not json_path.exists():
        print(f"Error: file not found: {json_path}")
        sys.exit(1)

    run_paths = _resolve_run_paths(json_path, explicit_run_dir)
    print(f"[ASV] Run folder: {run_paths.root}")

    orchestrator = ClaimOrchestrator(run_paths=run_paths)
    claims, citations = ClaimOrchestrator.load_claims_from_json(str(json_path))
    results = orchestrator.process_claims(claims, citations)

    total = sum(len(v) for v in results.values())
    print(f"\n[ASV] Done. {total} result entries written to {orchestrator.output_dir}/")
    print(f"[ASV] Log: {orchestrator._log_path}")


if __name__ == "__main__":
    main()
