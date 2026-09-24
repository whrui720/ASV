"""The gold set — Tier 0.4 (docs/TIER0_PLAN.md §7).

VALUE_PROPOSITION.md §2.5: *"There is no labelled set, so no precision, no
recall, no false-accusation rate. Every quality statement about ASV — including
the optimistic ones — is currently anecdote."*

This module owns the data: the record schema, the JSONL store, and the frozen
source snapshots that keep a pair reproducible after the publisher reorganises
its site. The labelling itself is human work; the tooling exists to make 250
labels affordable rather than to replace them.

**Labels are the Tier 0.2 verdict enum, deliberately.** A benchmark whose label
space differs from the system's output space measures nothing, which is why
0.4's schema blocks on 0.2 landing.

**Redistribution.** Gold pairs need the source text to stay reproducible, but
ASV must not become a way to redistribute paywalled full text. So:
open-access sources are snapshotted in full; everything else stores only the
excerpt window needed to justify the label, plus the sha256 of the full text.
``verify each corpus's licence before vendoring`` applies to SciFact, SCitance
and CiteME too — store identifiers and a fetch script, not their text, unless
the licence is checked.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from pydantic import BaseModel, Field

from asv.core.verdicts import Verdict

BENCHMARK_ROOT = Path("benchmarks")
GOLD_DIR = BENCHMARK_ROOT / "gold"
SOURCES_DIR = BENCHMARK_ROOT / "sources"
RESULTS_DIR = BENCHMARK_ROOT / "results"

#: The §6 miscitation taxonomy. Recorded now because it is free to capture
#: during labelling and expensive to add later, and it is what Tier 2.5's
#: detectors are measured against.
MISCITATION_TYPES = {
    "M1": "generalization drift (population or scope widened)",
    "M2": "hedge stripping (may be associated with -> causes)",
    "M3": "causal upgrade (correlation cited as mechanism)",
    "M4": "numeric drift (value, unit, denominator or window changed)",
    "M5": "temporal/scope drift (date or setting changed)",
    "M6": "chain citation (source attributes the finding to someone else)",
    "M7": "substantiation failure (source is unrelated or contradicts)",
}

#: Pairs whose negative label was manufactured by corrupting a verified
#: positive. They are essential for measuring per-type recall and useless for
#: measuring the false-accusation rate, because their difficulty distribution
#: is not the real one. Every report must separate them.
SEEDED_PROVENANCE = "seeded_negative"


class GoldSource(BaseModel):
    doi: Optional[str] = None
    url: Optional[str] = None
    title: Optional[str] = None
    content_quality: Optional[str] = None
    text_sha256: Optional[str] = None
    #: "full" when the whole extracted text is stored, "excerpt" when only the
    #: window needed for the label is (non-open-access sources).
    snapshot_kind: str = "excerpt"
    open_access: bool = False


class GoldEvidence(BaseModel):
    quote: str
    char_start: Optional[int] = None
    char_end: Optional[int] = None


class GoldPair(BaseModel):
    """One hand-labelled claim-source pair."""
    pair_id: str
    field: str                        # >= 3 distinct fields required overall
    provenance: str                   # asv_run | scifact | scitance | citeme | seeded_negative
    claim_text: str
    claim_id: Optional[str] = None
    run_id: Optional[str] = None
    source: GoldSource = Field(default_factory=GoldSource)

    label: Verdict
    label_reason: str = ""
    evidence_spans: List[GoldEvidence] = Field(default_factory=list)
    miscitation_types: List[str] = Field(default_factory=list)

    difficulty: str = "easy"          # easy | hard
    is_seeded_negative: bool = False
    #: The pair this was corrupted from, for seeded negatives.
    derived_from: Optional[str] = None

    annotator: Optional[str] = None
    annotated_at: Optional[str] = None
    #: Set when a second annotator labelled the same pair, for the >=20% overlap
    #: that makes Cohen's kappa computable.
    second_annotator: Optional[str] = None
    second_label: Optional[Verdict] = None
    adjudicated_by: Optional[str] = None
    adjudicated_label: Optional[Verdict] = None

    notes: str = ""

    @property
    def final_label(self) -> Verdict:
        return self.adjudicated_label or self.label

    @property
    def is_natural(self) -> bool:
        """Natural pairs are the only valid basis for a false-accusation rate."""
        return not self.is_seeded_negative


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

def gold_path(name: str = "gold") -> Path:
    return GOLD_DIR / f"{name}.jsonl"


def load_gold(name: str = "gold") -> List[GoldPair]:
    path = gold_path(name)
    if not path.exists():
        return []
    pairs: List[GoldPair] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        pairs.append(GoldPair(**json.loads(line)))
    return pairs


def save_gold(pairs: Iterable[GoldPair], name: str = "gold") -> Path:
    path = gold_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for p in pairs:
            f.write(json.dumps(p.model_dump(mode="json"), ensure_ascii=False) + "\n")
    return path


def upsert_gold(pair: GoldPair, name: str = "gold") -> Path:
    """Replace the pair with this ``pair_id``, or append it."""
    pairs = load_gold(name)
    by_id = {p.pair_id: i for i, p in enumerate(pairs)}
    if pair.pair_id in by_id:
        pairs[by_id[pair.pair_id]] = pair
    else:
        pairs.append(pair)
    return save_gold(pairs, name)


def next_pair_id(pairs: List[GoldPair], prefix: str = "asv-gold") -> str:
    used = {
        int(p.pair_id.rsplit("-", 1)[-1])
        for p in pairs
        if p.pair_id.startswith(prefix) and p.pair_id.rsplit("-", 1)[-1].isdigit()
    }
    return f"{prefix}-{(max(used) + 1 if used else 1):04d}"


# ---------------------------------------------------------------------------
# Frozen source snapshots
# ---------------------------------------------------------------------------

def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def store_source_text(
    text: str, *, open_access: bool, excerpt: Optional[str] = None
) -> GoldSource:
    """Snapshot source text and return the descriptor to attach to a pair.

    A gold pair whose source 403s next month is worthless, so the text is
    frozen here rather than re-fetched at evaluation time. For non-open-access
    sources only ``excerpt`` is written — enough to justify the label, not
    enough to be a redistribution channel.
    """
    SOURCES_DIR.mkdir(parents=True, exist_ok=True)
    digest = text_sha256(text)
    payload = text if open_access else (excerpt or text[:4000])
    (SOURCES_DIR / f"{digest}.txt").write_text(payload, encoding="utf-8")
    return GoldSource(
        text_sha256=digest,
        snapshot_kind="full" if open_access else "excerpt",
        open_access=open_access,
    )


def load_source_text(source: GoldSource) -> Optional[str]:
    if not source.text_sha256:
        return None
    path = SOURCES_DIR / f"{source.text_sha256}.txt"
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Composition reporting — a benchmark has to describe itself honestly
# ---------------------------------------------------------------------------

def composition(pairs: List[GoldPair]) -> Dict[str, Any]:
    """What this gold set is made of. Goes at the top of every report, so a
    reader can discount the numbers appropriately."""
    labels: Dict[str, int] = {}
    fields: Dict[str, int] = {}
    provenance: Dict[str, int] = {}
    types: Dict[str, int] = {}
    for p in pairs:
        labels[p.final_label.value] = labels.get(p.final_label.value, 0) + 1
        fields[p.field] = fields.get(p.field, 0) + 1
        provenance[p.provenance] = provenance.get(p.provenance, 0) + 1
        for t in p.miscitation_types:
            types[t] = types.get(t, 0) + 1

    natural = [p for p in pairs if p.is_natural]
    double = [p for p in pairs if p.second_label is not None]
    return {
        "total": len(pairs),
        "natural": len(natural),
        "seeded_negative": len(pairs) - len(natural),
        "natural_negatives": sum(
            1 for p in natural
            if p.final_label in (Verdict.NOT_SUBSTANTIATED, Verdict.CONTRADICTED)
        ),
        "fields": fields,
        "n_fields": len(fields),
        "labels": labels,
        "provenance": provenance,
        "miscitation_types": types,
        "double_annotated": len(double),
        "double_annotated_fraction": round(len(double) / len(pairs), 3) if pairs else 0.0,
        "generated_at": datetime.now().isoformat(),
    }


def readiness(pairs: List[GoldPair]) -> List[str]:
    """Unmet requirements from TIER0_PLAN.md §7, as plain sentences."""
    comp = composition(pairs)
    problems = []
    if comp["total"] < 200:
        problems.append(f"{comp['total']} pairs; the target is 200-300.")
    if comp["n_fields"] < 3:
        problems.append(f"{comp['n_fields']} field(s); at least 3 are required.")
    if comp["natural_negatives"] < 15:
        problems.append(
            f"{comp['natural_negatives']} naturally-occurring negatives; at least 15 are "
            "needed, because the false-accusation rate cannot be measured on seeded ones."
        )
    if comp["double_annotated_fraction"] < 0.2:
        problems.append(
            f"{comp['double_annotated_fraction']:.0%} double-annotated; 20% is the minimum "
            "for a meaningful inter-annotator agreement figure."
        )
    return problems
