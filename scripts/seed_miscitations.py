"""Generate hard negatives by corrupting verified positives — Tier 0.4 §7.3.

This is what makes a 200-300 pair gold set affordable. Naturally occurring
miscitations run at roughly 1 in 6 and are expensive to find; seeded corruption
produces them on demand, along one taxonomy axis at a time, which is also
exactly what VALUE_PROPOSITION.md §8's "recall on seeded errors" metric and §6's
M1-M7 detectors need to be measured against.

One verified positive yields up to six hard negatives, so ~60 verified
positives plus ~40 natural pairs comfortably reaches 250.

**A human accepts or rejects every mutation.** The model proposes; the person
approves on a one-line diff, which takes a few seconds. That review is the
manual gate, and it is not optional: an unreviewed mutation can easily still be
true of the source, which would poison the labels in the direction that matters
most.

**Seeded negatives are tracked separately, forever.** They are manufactured to
be detectable, so including them in the false-accusation rate would flatter the
system in the one dimension VALUE_PROPOSITION.md §10 calls critical. The report
separates them; ``metrics.false_accusation_rate`` is documented as natural-only.

Usage::

    python scripts/seed_miscitations.py --limit 20            # propose + review
    python scripts/seed_miscitations.py --limit 20 --dry-run  # just look
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from asv.benchmark.gold import (  # noqa: E402
    MISCITATION_TYPES, SEEDED_PROVENANCE, GoldPair, load_gold, next_pair_id, save_gold,
)
from asv.core.verdicts import Verdict  # noqa: E402
from asv.extraction.llm_client import LLMClient  # noqa: E402

# Expected label per mutation type. M2 is the interesting one: stripping a hedge
# usually leaves a claim the source *partially* supports rather than one it
# refutes, and getting that distinction right is most of what separates a
# useful finding from a false accusation.
TYPE_LABEL = {
    "M1": Verdict.NOT_SUBSTANTIATED,
    "M2": Verdict.PARTIALLY_SUBSTANTIATED,
    "M3": Verdict.NOT_SUBSTANTIATED,
    "M4": Verdict.CONTRADICTED,
    "M5": Verdict.NOT_SUBSTANTIATED,
    "M6": Verdict.NOT_SUBSTANTIATED,
}

PROMPT = """You are building a benchmark of miscited claims for a citation-auditing tool.

Below is a claim that a cited source genuinely DOES support, plus the passage
from that source.

Claim: "{claim}"

Source passage:
{passage}

Produce one corrupted version of the claim for each mutation type below. Each
corruption must:
- change the claim ONLY along that one axis, keeping everything else identical;
- stay fluent and plausible, as a real miscitation would be — do not make it
  absurd or obviously wrong;
- become genuinely unsupported (or, for M2, only partially supported) by the
  passage above.

If a mutation type does not apply to this claim (e.g. M4 on a claim with no
number), return null for it rather than inventing something.

Mutation types:
{types}

Return JSON:
{{"M1": {{"claim": "...", "what_changed": "..."}} or null, "M2": ..., ...}}
"""


def propose(llm: LLMClient, pair: GoldPair, passage: str) -> Dict[str, dict]:
    types = "\n".join(f"- {k}: {v}" for k, v in MISCITATION_TYPES.items() if k in TYPE_LABEL)
    prompt = PROMPT.format(claim=pair.claim_text, passage=passage[:4000], types=types)
    try:
        response = llm.call_llm(
            prompt, response_format="json", task_name="quant_script_generation",
            system_message="You construct benchmark data for a citation auditor.",
        )
    except Exception as e:
        print(f"    proposal failed: {e}")
        return {}
    return response if isinstance(response, dict) else {}


def review(pair: GoldPair, mtype: str, proposal: dict) -> bool:
    """The manual gate. Returns True if the human accepts this mutation."""
    print(f"\n  [{mtype}] {MISCITATION_TYPES[mtype]}")
    print(f"    original:  {pair.claim_text}")
    print(f"    corrupted: {proposal.get('claim')}")
    print(f"    changed:   {proposal.get('what_changed')}")
    print(f"    -> would be labelled {TYPE_LABEL[mtype].value}")
    answer = input("    accept? [y/N/q] ").strip().lower()
    if answer == "q":
        raise KeyboardInterrupt
    return answer == "y"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--name", default="gold")
    ap.add_argument("--limit", type=int, default=10,
                    help="how many verified positives to corrupt this session")
    ap.add_argument("--dry-run", action="store_true",
                    help="print proposals without writing anything")
    args = ap.parse_args()

    pairs = load_gold(args.name)
    if not pairs:
        print("No gold set yet. Run scripts/build_gold_seed.py first.")
        sys.exit(1)

    already_derived = {p.derived_from for p in pairs if p.derived_from}
    positives = [
        p for p in pairs
        if p.final_label == Verdict.SUBSTANTIATED
        and p.annotator            # only human-verified positives may be corrupted
        and not p.is_seeded_negative
        and p.pair_id not in already_derived
    ]
    if not positives:
        print(
            "No human-verified `substantiated` pairs available to corrupt.\n"
            "Label some positives first — a seeded negative is only as trustworthy "
            "as the positive it was derived from."
        )
        sys.exit(1)

    print(f"{len(positives)} verified positive(s) available; taking {args.limit}.")
    llm = LLMClient()
    annotator = input("Your initials (recorded as the reviewer): ").strip() or "unknown"
    created: List[GoldPair] = []

    try:
        for pair in positives[:args.limit]:
            print(f"\n{'=' * 70}\n{pair.pair_id}: {pair.claim_text[:100]}")
            passage = (
                pair.evidence_spans[0].quote if pair.evidence_spans else pair.notes
            )
            if not passage:
                print("  no passage stored for this pair — skipping")
                continue

            proposals = propose(llm, pair, passage)
            for mtype, proposal in proposals.items():
                if mtype not in TYPE_LABEL or not isinstance(proposal, dict):
                    continue
                if not proposal.get("claim"):
                    continue
                if args.dry_run:
                    print(f"  [{mtype}] {proposal['claim']}")
                    continue
                if not review(pair, mtype, proposal):
                    continue
                created.append(GoldPair(
                    pair_id=next_pair_id(pairs + created, prefix="asv-seed"),
                    field=pair.field,
                    provenance=SEEDED_PROVENANCE,
                    claim_text=proposal["claim"],
                    source=pair.source,
                    label=TYPE_LABEL[mtype],
                    label_reason=f"{mtype}: {proposal.get('what_changed', '')}",
                    evidence_spans=pair.evidence_spans,
                    miscitation_types=[mtype],
                    difficulty="hard",
                    is_seeded_negative=True,
                    derived_from=pair.pair_id,
                    annotator=annotator,
                    annotated_at=datetime.now().isoformat(),
                    notes=pair.notes,
                ))
    except KeyboardInterrupt:
        print("\nStopping early; keeping what was accepted so far.")

    if args.dry_run:
        print("\n--dry-run: nothing written.")
        return
    if not created:
        print("\nNo mutations accepted; nothing written.")
        return

    save_gold(pairs + created, args.name)
    print(f"\nAdded {len(created)} seeded negative(s).")
    print(json.dumps(
        {t: sum(1 for c in created if t in c.miscitation_types) for t in TYPE_LABEL},
        indent=2,
    ))
    print(
        "\nReminder: these are synthetic. eval_gold.py reports them separately, "
        "and the false-accusation rate is computed on natural pairs only."
    )


if __name__ == "__main__":
    main()
