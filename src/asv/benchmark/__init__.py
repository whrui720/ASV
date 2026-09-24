"""Gold-set benchmark package — Tier 0.4.

The labelling is human work. This package is the scaffolding that makes 250
labels affordable: a schema that matches the verdict ontology exactly, frozen
source snapshots so a pair stays reproducible, and the metrics that
VALUE_PROPOSITION.md §8 says have to be published before any quality claim
about ASV is defensible.
"""

from .gold import GoldEvidence, GoldPair, GoldSource, load_gold, save_gold, upsert_gold

__all__ = [
    "GoldPair",
    "GoldSource",
    "GoldEvidence",
    "load_gold",
    "save_gold",
    "upsert_gold",
]
