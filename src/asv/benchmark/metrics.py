"""Metrics for the gold set — Tier 0.4 / VALUE_PROPOSITION.md §8.

The ordering in §8 is deliberate and preserved here: **false-accusation rate is
the metric that decides whether this is a product or a liability.** A tool that
tells a researcher their citation is wrong when it isn't gets uninstalled after
the second occurrence.

Two subtleties this module enforces rather than documents:

1. The false-accusation rate is computed on **natural pairs only**. Seeded
   corruptions are manufactured to be detectable; including them would flatter
   the system in exactly the dimension that matters.
2. Calibration is computed only over **non-abstentions**, because abstentions
   carry no confidence by construction (Tier 0.2).
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from asv.core.verdicts import ACCUSATION_VERDICTS, Verdict

VERDICTS: List[Verdict] = list(Verdict)

#: What the human said when they think the citation is fine. An ASV accusation
#: against one of these is a false accusation.
_SUPPORTIVE = {Verdict.SUBSTANTIATED, Verdict.PARTIALLY_SUBSTANTIATED}


def confusion_matrix(
    pairs: Sequence[Tuple[Verdict, Verdict]]
) -> Dict[str, Dict[str, int]]:
    """``{gold: {predicted: n}}`` over the full ontology."""
    matrix = {g.value: {p.value: 0 for p in VERDICTS} for g in VERDICTS}
    for gold, pred in pairs:
        matrix[gold.value][pred.value] += 1
    return matrix


def false_accusation_rate(
    pairs: Sequence[Tuple[Verdict, Verdict]]
) -> Dict[str, Optional[float]]:
    """Of the claims ASV accused, how many did the human judge correctly cited?

    Pass **natural pairs only**. VALUE_PROPOSITION.md §8 target: <5%, published.
    """
    accused = [(g, p) for g, p in pairs if p in ACCUSATION_VERDICTS]
    wrong = [(g, p) for g, p in accused if g in _SUPPORTIVE]
    return {
        "accusations": len(accused),
        "false_accusations": len(wrong),
        "rate": round(len(wrong) / len(accused), 4) if accused else None,
    }


def per_class(pairs: Sequence[Tuple[Verdict, Verdict]]) -> Dict[str, Dict[str, Optional[float]]]:
    out: Dict[str, Dict[str, Optional[float]]] = {}
    for v in VERDICTS:
        tp = sum(1 for g, p in pairs if g == v and p == v)
        fp = sum(1 for g, p in pairs if g != v and p == v)
        fn = sum(1 for g, p in pairs if g == v and p != v)
        precision = tp / (tp + fp) if (tp + fp) else None
        recall = tp / (tp + fn) if (tp + fn) else None
        f1 = (
            2 * precision * recall / (precision + recall)
            if precision and recall else None
        )
        out[v.value] = {
            "support": tp + fn,
            "precision": round(precision, 4) if precision is not None else None,
            "recall": round(recall, 4) if recall is not None else None,
            "f1": round(f1, 4) if f1 is not None else None,
        }
    return out


def abstention_correctness(
    pairs: Sequence[Tuple[Verdict, Verdict]]
) -> Dict[str, Optional[float]]:
    """Of the claims ASV declined to judge, how many were genuinely unjudgeable?

    A gold label of ``not_checkable`` means the human agreed there was nothing
    to check. §8 target: >90%.
    """
    abstained = [(g, p) for g, p in pairs if p == Verdict.NOT_CHECKABLE]
    correct = [(g, p) for g, p in abstained if g == Verdict.NOT_CHECKABLE]
    return {
        "abstentions": len(abstained),
        "correct": len(correct),
        "rate": round(len(correct) / len(abstained), 4) if abstained else None,
    }


def calibration(
    scored: Sequence[Tuple[bool, float]], bins: int = 10
) -> Dict[str, object]:
    """Reliability curve and expected calibration error.

    ``scored`` is ``(was_correct, confidence)`` for non-abstentions only.
    §8 target: ECE < 0.1.
    """
    if not scored:
        return {"ece": None, "curve": []}

    buckets: List[List[Tuple[bool, float]]] = [[] for _ in range(bins)]
    for correct, conf in scored:
        idx = min(int(conf * bins), bins - 1)
        buckets[idx].append((correct, conf))

    curve = []
    ece = 0.0
    n = len(scored)
    for i, bucket in enumerate(buckets):
        if not bucket:
            continue
        acc = sum(1 for c, _ in bucket if c) / len(bucket)
        avg_conf = sum(c for _, c in bucket) / len(bucket)
        ece += (len(bucket) / n) * abs(acc - avg_conf)
        curve.append({
            "bin": f"{i / bins:.1f}-{(i + 1) / bins:.1f}",
            "n": len(bucket),
            "accuracy": round(acc, 4),
            "avg_confidence": round(avg_conf, 4),
        })
    return {"ece": round(ece, 4), "curve": curve}


def cohens_kappa(a: Sequence[str], b: Sequence[str]) -> Optional[float]:
    """Inter-annotator agreement, corrected for chance.

    Without this, the gold set's own error rate is unknown — which is exactly
    the criticism VALUE_PROPOSITION.md levels at SciFact, where a 2026 audit
    found 5.3% gold-label errors. A benchmark published without an agreement
    statistic is an opinion with a confusion matrix attached.
    """
    if not a or len(a) != len(b):
        return None
    n = len(a)
    observed = sum(1 for x, y in zip(a, b) if x == y) / n
    labels = set(a) | set(b)
    expected = sum(
        (sum(1 for x in a if x == label) / n) * (sum(1 for y in b if y == label) / n)
        for label in labels
    )
    if expected == 1.0:
        return 1.0
    return round((observed - expected) / (1 - expected), 4)


def determinism(verdict_runs: Iterable[Sequence[Verdict]]) -> Optional[float]:
    """Fraction of claims whose verdict is identical across repeated runs.

    §8 target: >95%. VALUE_PROPOSITION.md §10 names LLM nondeterminism as a
    threat to the audit trail; this is how it gets measured rather than assumed.
    """
    runs = [list(r) for r in verdict_runs]
    if len(runs) < 2 or not runs[0]:
        return None
    agree = sum(
        1 for i in range(len(runs[0]))
        if all(run[i] == runs[0][i] for run in runs)
    )
    return round(agree / len(runs[0]), 4)


def seeded_recall_by_type(
    rows: Sequence[Tuple[List[str], Verdict, Verdict]]
) -> Dict[str, Dict[str, object]]:
    """Detection rate on deliberately corrupted pairs, per M1-M7 category.

    ``rows`` is ``(miscitation_types, gold, predicted)``. §8 target: >70% per
    category. Reported separately from everything else, because these are
    synthetic.
    """
    out: Dict[str, Dict[str, object]] = {}
    for types, gold, pred in rows:
        detected = pred in ACCUSATION_VERDICTS or pred == Verdict.PARTIALLY_SUBSTANTIATED
        for t in types or ["unlabelled"]:
            bucket = out.setdefault(t, {"n": 0, "detected": 0})
            bucket["n"] += 1  # type: ignore[operator]
            if detected:
                bucket["detected"] += 1  # type: ignore[operator]
    for t, bucket in out.items():
        n = bucket["n"]
        bucket["recall"] = round(bucket["detected"] / n, 4) if n else None  # type: ignore[index]
    return out
