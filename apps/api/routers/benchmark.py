"""Gold-set annotation endpoints — Tier 0.4 (TIER0_PLAN.md §7.4).

Annotation speed *is* the project: 250 pairs at 3 minutes each is 12.5 hours; at
90 seconds each it is 6. The expensive parts of an annotation tool — rendering a
claim next to its retrieved passages and its source — already exist in this app,
so the benchmark route reuses them rather than standing up a second UI.

These endpoints write to ``benchmarks/gold/*.jsonl`` in the repo, which is
deliberate: the gold set is version-controlled data, and a label that is not in
git is a label nobody can reproduce.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from asv.benchmark.gold import (
    MISCITATION_TYPES, GoldEvidence, GoldPair, composition, load_gold, readiness,
    upsert_gold,
)
from asv.core.verdicts import Verdict

router = APIRouter(prefix="/api/benchmark", tags=["benchmark"])


class LabelRequest(BaseModel):
    pair_id: str
    label: Verdict
    annotator: str
    label_reason: str = ""
    evidence_spans: List[GoldEvidence] = Field(default_factory=list)
    miscitation_types: List[str] = Field(default_factory=list)
    difficulty: str = "easy"
    notes: str = ""
    #: True when this is the *second* independent pass over a pair. The second
    #: label is stored alongside the first rather than replacing it, because
    #: overwriting it would destroy the only basis for an inter-annotator
    #: agreement figure — and a benchmark without one is an opinion with a
    #: confusion matrix attached.
    second_pass: bool = False


class GoldStats(BaseModel):
    composition: Dict[str, Any]
    readiness_problems: List[str]
    miscitation_types: Dict[str, str]
    labelled: int
    unlabelled: int


@router.get("/{name}/stats", response_model=GoldStats)
def stats(name: str = "gold") -> GoldStats:
    pairs = load_gold(name)
    labelled = sum(1 for p in pairs if p.annotator)
    return GoldStats(
        composition=composition(pairs),
        readiness_problems=readiness(pairs),
        miscitation_types=MISCITATION_TYPES,
        labelled=labelled,
        unlabelled=len(pairs) - labelled,
    )


@router.get("/{name}/pairs", response_model=List[GoldPair])
def list_pairs(
    name: str = "gold",
    unlabelled_only: bool = False,
    needs_second_pass: bool = False,
    limit: int = 200,
) -> List[GoldPair]:
    """Pairs to work through.

    ``needs_second_pass`` surfaces already-labelled pairs for a *different*
    annotator, which is how the >=20% double-annotated overlap gets built.
    """
    pairs = load_gold(name)
    if unlabelled_only:
        pairs = [p for p in pairs if not p.annotator]
    if needs_second_pass:
        pairs = [p for p in pairs if p.annotator and p.second_label is None]
    return pairs[:limit]


@router.get("/{name}/pairs/{pair_id}", response_model=GoldPair)
def get_pair(pair_id: str, name: str = "gold") -> GoldPair:
    for p in load_gold(name):
        if p.pair_id == pair_id:
            return p
    raise HTTPException(status_code=404, detail=f"No gold pair: {pair_id}")


@router.post("/{name}/label", response_model=GoldPair)
def label_pair(req: LabelRequest, name: str = "gold") -> GoldPair:
    pairs = {p.pair_id: p for p in load_gold(name)}
    pair = pairs.get(req.pair_id)
    if pair is None:
        raise HTTPException(status_code=404, detail=f"No gold pair: {req.pair_id}")

    if req.second_pass:
        if pair.annotator == req.annotator:
            raise HTTPException(
                status_code=400,
                detail=(
                    "The second pass must be made by a different annotator — "
                    "agreement with yourself measures nothing."
                ),
            )
        pair.second_annotator = req.annotator
        pair.second_label = req.label
    else:
        pair.label = req.label
        pair.label_reason = req.label_reason
        pair.evidence_spans = req.evidence_spans
        pair.miscitation_types = [
            t for t in req.miscitation_types if t in MISCITATION_TYPES
        ]
        pair.difficulty = req.difficulty
        pair.annotator = req.annotator
        pair.annotated_at = datetime.now().isoformat()
        if req.notes:
            pair.notes = req.notes

    upsert_gold(pair, name)
    return pair


class AdjudicateRequest(BaseModel):
    pair_id: str
    adjudicated_label: Verdict
    adjudicated_by: str


@router.post("/{name}/adjudicate", response_model=GoldPair)
def adjudicate(req: AdjudicateRequest, name: str = "gold") -> GoldPair:
    """Settle a disagreement between two annotators.

    The adjudicated label becomes ``final_label``; both original labels are
    kept, so kappa still reflects the raw disagreement rather than the
    tidied-up version."""
    pairs = {p.pair_id: p for p in load_gold(name)}
    pair = pairs.get(req.pair_id)
    if pair is None:
        raise HTTPException(status_code=404, detail=f"No gold pair: {req.pair_id}")
    pair.adjudicated_label = req.adjudicated_label
    pair.adjudicated_by = req.adjudicated_by
    upsert_gold(pair, name)
    return pair


@router.get("/{name}/disagreements", response_model=List[GoldPair])
def disagreements(name: str = "gold") -> List[GoldPair]:
    return [
        p for p in load_gold(name)
        if p.second_label is not None
        and p.second_label != p.label
        and p.adjudicated_label is None
    ]
