"""Seed the gold set from ASV's own runs — Tier 0.4 (TIER0_PLAN.md §7.2).

Every claim in an existing run folder whose batch obtained judgeable full text
is a candidate gold pair, already carrying the retrieved passages. This script
turns those into *unlabelled* ``GoldPair`` records so a human only has to make
the judgment, not assemble the context.

It labels nothing. ``label`` is set to ``not_checkable`` as a placeholder and
``annotator`` is left empty; the annotation UI (``/runs/:runId/benchmark``) or
``--stdin-labels`` fills them in.

Usage::

    python scripts/build_gold_seed.py                      # all runs
    python scripts/build_gold_seed.py --run hsv_cancer__20260706_192057
    python scripts/build_gold_seed.py --field virology --require-full-text

Running it twice is safe: pairs are keyed on (run, claim) and updated in place.

Note on ≥3 fields: this seeder only produces pairs from papers you have already
run, so a corpus of one virology review yields one field. Run ASV on at least
two papers from other disciplines — preferably open-access ones, so the
snapshots can be stored in full — before the gold set is usable.
"""

import argparse
import sys
from pathlib import Path
from typing import Dict, List, Optional

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from asv.benchmark.gold import (  # noqa: E402
    GoldEvidence, GoldPair, GoldSource, composition, load_gold, readiness, save_gold,
)
from asv.core.run_paths import RUNS_ROOT_DIR, RunPaths  # noqa: E402
from asv.core.verdicts import ContentQuality, Verdict  # noqa: E402

sys.path.insert(0, str(_ROOT))
from apps.api.services import read_model  # noqa: E402

_OA_HOSTS = (
    "europepmc.org", "ncbi.nlm.nih.gov", "pmc.ncbi.nlm.nih.gov", "arxiv.org",
    "biorxiv.org", "medrxiv.org", "plos.org", "doaj.org", "frontiersin.org",
    "mdpi.com", "biomedcentral.com", "nature.com/articles/s41598",
)


def _is_open_access(url: Optional[str]) -> bool:
    """Conservative: only hosts whose licence permits redistribution get a full
    snapshot. Everything else is stored as an excerpt."""
    return bool(url) and any(h in url for h in _OA_HOSTS)


def seed_from_run(
    run_dir: Path, field: str, require_full_text: bool, existing: Dict[str, GoldPair]
) -> List[GoldPair]:
    run_paths = RunPaths.from_existing(run_dir)
    rows = read_model.build_claim_rows(run_paths, use_cache=False)
    out: List[GoldPair] = []

    for row in rows:
        batch = row.batch
        if batch is None or not batch.download_successful:
            continue
        if require_full_text and batch.content_quality != ContentQuality.FULL_TEXT:
            continue

        key = f"{run_dir.name}:{row.claim_id}"
        chunks = (
            (row.result.validation_metadata or {}).get("rag_chunks", [])
            if row.result else []
        )
        evidence = [
            GoldEvidence(quote=e.quote, char_start=e.char_start, char_end=e.char_end)
            for e in (row.result.evidence if row.result else [])
        ]
        # Fall back to the retrieved passages so the annotator has context even
        # when ASV itself produced no evidence.
        excerpt = "\n\n---\n\n".join(
            c.get("text", "") for c in chunks if isinstance(c, dict)
        )

        prior = existing.get(key)
        pair = GoldPair(
            pair_id=prior.pair_id if prior else key,
            field=field,
            provenance="asv_run",
            claim_text=row.text,
            claim_id=row.claim_id,
            run_id=run_dir.name,
            source=GoldSource(
                doi=(row.citation.details.doi if row.citation and row.citation.details else None),
                url=batch.winning_url,
                title=(row.citation.details.title if row.citation and row.citation.details else None),
                content_quality=batch.content_quality.value if batch.content_quality else None,
                open_access=_is_open_access(batch.winning_url),
                snapshot_kind="excerpt",
            ),
            # Placeholder: a human sets the real label. Deliberately the
            # abstention, so an unlabelled pair can never be mistaken for a
            # verified positive if it leaks into a report.
            label=prior.label if prior else Verdict.NOT_CHECKABLE,
            label_reason=prior.label_reason if prior else "",
            evidence_spans=prior.evidence_spans if prior else evidence,
            annotator=prior.annotator if prior else None,
            annotated_at=prior.annotated_at if prior else None,
            notes=(prior.notes if prior else excerpt[:4000]),
        )
        out.append(pair)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run", help="a single run folder name; default is all of them")
    ap.add_argument("--field", default="virology",
                    help="research field label for these pairs (>=3 needed overall)")
    ap.add_argument("--require-full-text", action="store_true",
                    help="only seed from batches whose source was classified full_text")
    ap.add_argument("--name", default="gold", help="gold set name (benchmarks/gold/<name>.jsonl)")
    args = ap.parse_args()

    root = Path(RUNS_ROOT_DIR)
    run_dirs = (
        [root / args.run] if args.run
        else sorted(p for p in root.iterdir() if p.is_dir() and "__" in p.name)
    )

    existing = {p.pair_id: p for p in load_gold(args.name)}
    seeded: List[GoldPair] = []
    for d in run_dirs:
        if not d.is_dir():
            print(f"skip (not a directory): {d}")
            continue
        pairs = seed_from_run(d, args.field, args.require_full_text, existing)
        print(f"{d.name}: {len(pairs)} candidate pair(s)")
        seeded.extend(pairs)

    merged = {**existing, **{p.pair_id: p for p in seeded}}
    path = save_gold(list(merged.values()), args.name)

    pairs = list(merged.values())
    unlabelled = sum(1 for p in pairs if p.annotator is None)
    print(f"\nWrote {path} — {len(pairs)} pairs, {unlabelled} still unlabelled.")
    print("Composition:", composition(pairs))

    problems = readiness(pairs)
    if problems:
        print("\nNot yet a usable gold set:")
        for p in problems:
            print(f"  - {p}")
        print(
            "\nLabel pairs at /runs/<run_id>/benchmark in the web UI "
            "(keys 1-5 to judge, h to mark hard)."
        )
    else:
        print("\nGold set meets the Tier 0.4 structural requirements.")


if __name__ == "__main__":
    main()
