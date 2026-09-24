"""Evaluate the verdict layer against the gold set — Tier 0.4 (TIER0_PLAN.md §7.5).

Runs the **validator only**, against frozen source text, deliberately bypassing
acquisition. That isolation is the point: with a 31% download rate, an
end-to-end evaluation measures source acquisition and reports it as judgment
quality.

Produces ``benchmarks/results/<timestamp>/report.json`` and ``report.md``, plus
a ``latest`` copy. "Published", per VALUE_PROPOSITION.md, means committed in the
repo and linked from the README — and regenerated whenever the judgment layer
changes.

Usage::

    python scripts/eval_gold.py
    python scripts/eval_gold.py --repeats 3     # also measure determinism
    python scripts/eval_gold.py --limit 25      # quick pass while iterating
"""

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from asv.benchmark import gold as gold_mod  # noqa: E402
from asv.benchmark.gold import GoldPair, composition, load_gold, readiness  # noqa: E402
from asv.benchmark.metrics import (  # noqa: E402
    abstention_correctness, calibration, cohens_kappa, confusion_matrix, determinism,
    false_accusation_rate, per_class, seeded_recall_by_type,
)
from asv.core.verdicts import ACCUSATION_VERDICTS, Verdict  # noqa: E402
from asv.extraction.llm_client import LLMClient  # noqa: E402
from asv.validator.llm_verifier import LLMVerifier  # noqa: E402


def source_text_for(pair: GoldPair) -> Optional[str]:
    """Frozen snapshot first; the stored excerpt is the fallback."""
    text = gold_mod.load_source_text(pair.source)
    if text:
        return text
    return pair.notes or None


def judge(verifier: LLMVerifier, pair: GoldPair) -> Tuple[Verdict, Optional[float]]:
    text = source_text_for(pair)
    if not text:
        return Verdict.NOT_CHECKABLE, None
    out = verifier.verify_claim_against_source(
        pair.claim_text, text, source_url=pair.source.url or "https://example.invalid",
    )
    return out["verdict"], out.get("confidence")


def _pct(value: Optional[float], places: int = 1) -> str:
    return "—" if value is None else f"{value * 100:.{places}f}%"


def _num(value: Optional[float], places: int = 2) -> str:
    return "—" if value is None else f"{value:.{places}f}"


def render_markdown(report: Dict) -> str:
    comp = report["composition"]
    far = report["false_accusation_rate"]
    abst = report["abstention_correctness"]
    lines = [
        "# ASV verdict-layer evaluation",
        "",
        f"**Generated:** {report['generated_at']}  ",
        f"**Prompt version:** `{report['prompt_version']}`  ",
        f"**Gold set:** {comp['total']} pairs across {comp['n_fields']} field(s)",
        "",
        "## Read this first",
        "",
        "The evaluation runs the validator against **frozen source text**, not the",
        "live acquisition layer. It measures judgment quality only; the checkable",
        "rate reported on a real run is a separate (and currently much worse) number.",
        "",
        f"Of the {comp['total']} pairs, **{comp['natural']} are natural** and",
        f"**{comp['seeded_negative']} are seeded corruptions**. Seeded pairs are",
        "manufactured to be detectable, so they are excluded from the",
        "false-accusation rate and reported separately under per-type recall.",
        "",
        "## The metric that decides whether this ships",
        "",
        "| Metric | Value | Target |",
        "|---|---|---|",
    ]
    ece = report["calibration"]["ece"]
    det = report["determinism"]
    kappa = report["inter_annotator_kappa"]
    lines += [
        f"| **False-accusation rate** (natural pairs) | {_pct(far['rate'])} "
        f"({far['false_accusations']}/{far['accusations']}) | **< 5%** |",
        f"| Abstention correctness | {_pct(abst['rate'])} "
        f"({abst['correct']}/{abst['abstentions']}) | > 90% |",
        f"| Calibration (ECE) | {_num(ece, 3)} | < 0.10 |",
        f"| Determinism | {'not measured' if det is None else _pct(det)} | > 95% |",
        f"| Inter-annotator agreement (kappa) | "
        f"{'not measured' if kappa is None else kappa} | report it |",
        "",
        "## Per-class performance",
        "",
        "| Verdict | Support | Precision | Recall | F1 |",
        "|---|---:|---:|---:|---:|",
    ]
    for verdict, m in report["per_class"].items():
        lines.append(
            f"| {verdict} | {m['support']} | {_num(m['precision'])} | "
            f"{_num(m['recall'])} | {_num(m['f1'])} |"
        )

    lines += ["", "## Confusion matrix (gold \\ predicted)", "", "| |" + "|".join(
        v.value for v in Verdict) + "|", "|---|" + "---|" * len(Verdict)]
    for g, row in report["confusion_matrix"].items():
        lines.append(f"| **{g}** |" + "|".join(str(row[p.value]) for p in Verdict) + "|")

    if report["seeded_recall"]:
        lines += ["", "## Recall on seeded errors (synthetic)", "",
                  "| Type | n | Detected | Recall | Target |", "|---|---:|---:|---:|---:|"]
        from asv.benchmark.gold import MISCITATION_TYPES
        for t, m in sorted(report["seeded_recall"].items()):
            lines.append(
                f"| {t} — {MISCITATION_TYPES.get(t, '')} | {m['n']} | {m['detected']} | "
                f"{_pct(m.get('recall'), 0)} | > 70% |"
            )

    if report["readiness_problems"]:
        lines += ["", "## Caveats on the gold set itself", ""]
        lines += [f"- {p}" for p in report["readiness_problems"]]
        lines += [
            "",
            "Until these are resolved, treat every number above as indicative, not",
            "publishable.",
        ]

    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--name", default="gold")
    ap.add_argument("--limit", type=int, default=0, help="evaluate only the first N pairs")
    ap.add_argument("--repeats", type=int, default=1,
                    help="repeat the run N times to measure determinism")
    args = ap.parse_args()

    pairs = load_gold(args.name)
    labelled = [p for p in pairs if p.annotator]
    if not labelled:
        print("No labelled pairs. Seed with build_gold_seed.py, then label them.")
        sys.exit(1)
    if args.limit:
        labelled = labelled[:args.limit]

    print(f"Evaluating {len(labelled)} labelled pairs, {args.repeats} repeat(s)…")
    verifier = LLMVerifier(LLMClient())

    runs: List[List[Verdict]] = []
    confidences: List[Optional[float]] = []
    for r in range(args.repeats):
        verdicts: List[Verdict] = []
        for i, pair in enumerate(labelled, 1):
            verdict, conf = judge(verifier, pair)
            verdicts.append(verdict)
            if r == 0:
                confidences.append(conf)
            if i % 25 == 0:
                print(f"  repeat {r + 1}: {i}/{len(labelled)}")
        runs.append(verdicts)

    predicted = runs[0]
    scored = [(p.final_label, v) for p, v in zip(labelled, predicted)]
    natural = [(p.final_label, v) for p, v in zip(labelled, predicted) if p.is_natural]
    seeded = [
        (p.miscitation_types, p.final_label, v)
        for p, v in zip(labelled, predicted) if p.is_seeded_negative
    ]

    calib_input = [
        (gold == pred, conf)
        for (gold, pred), conf in zip(scored, confidences)
        if conf is not None and pred != Verdict.NOT_CHECKABLE
    ]

    double = [p for p in labelled if p.second_label is not None]
    kappa = cohens_kappa(
        [p.label.value for p in double],
        [p.second_label.value for p in double],  # type: ignore[union-attr]
    ) if double else None

    from asv.validator.config import SOURCE_VERIFICATION_PROMPT_VERSION
    report = {
        "generated_at": datetime.now().isoformat(),
        "prompt_version": SOURCE_VERIFICATION_PROMPT_VERSION,
        "n_evaluated": len(labelled),
        "composition": composition(labelled),
        "readiness_problems": readiness(pairs),
        "confusion_matrix": confusion_matrix(scored),
        "per_class": per_class(scored),
        # Natural pairs only — this is the number that decides whether ASV is a
        # product or a liability, and seeded corruptions would flatter it.
        "false_accusation_rate": false_accusation_rate(natural),
        "false_accusation_rate_all_pairs_do_not_publish":
            false_accusation_rate(scored),
        "abstention_correctness": abstention_correctness(scored),
        "calibration": calibration(calib_input),
        "determinism": determinism(runs) if args.repeats > 1 else None,
        "inter_annotator_kappa": kappa,
        "seeded_recall": seeded_recall_by_type(seeded),
    }

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = gold_mod.RESULTS_DIR / stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (out_dir / "report.md").write_text(render_markdown(report), encoding="utf-8")

    latest = gold_mod.RESULTS_DIR / "latest"
    latest.mkdir(parents=True, exist_ok=True)
    for f in ("report.json", "report.md"):
        shutil.copy(out_dir / f, latest / f)

    far = report["false_accusation_rate"]
    print(f"\nWrote {out_dir}/report.md (and benchmarks/results/latest/)")
    print(f"  false-accusation rate (natural): {_pct(far['rate'])}"
          f"  [{far['false_accusations']}/{far['accusations']}]")
    for problem in report["readiness_problems"]:
        print(f"  caveat: {problem}")


if __name__ == "__main__":
    main()
