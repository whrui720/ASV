"""Probe the free bibliographic APIs and print their live response shapes.

TIER0_PLAN.md §6.8: do not code the reference matcher against remembered field
names. Free scholarly APIs change, and ``index_clients.py`` extracts a dozen
fields from five of them. This script hits each service with five references of
known difficulty and prints, for each: the request URL, the HTTP status, the
rate-limit headers, and the JSON path to title / authors / year / DOI /
retraction status.

Run it before touching ``index_clients.py``, and whenever the reference audit
starts returning nothing::

    python scripts/probe_existence_apis.py
    python scripts/probe_existence_apis.py --json > docs/api_probe.json

Requires network. Nothing else in the test suite does.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from asv.sourcefinder.index_clients import BibliographicIndexes, IndexResponse  # noqa: E402

# Five references chosen to exercise the decision boundaries the matcher cares
# about, not just the happy path.
PROBES = [
    {
        "label": "has an inline DOI (the easy case)",
        "doi": "10.1038/nm.3089",
        "title": "Oncolytic viruses in cancer therapy",
        "first_author": "Russell",
        "year": 2012,
        "journal": "Nature Medicine",
    },
    {
        "label": "biomedical, no DOI in the reference string",
        "title": (
            "Glycoprotein C of herpes simplex virus type 1 plays a principal role "
            "in the adsorption of virus to cells and in infectivity"
        ),
        "first_author": "Herold",
        "year": 1991,
        "journal": "J Virol",
        "volume": "65",
        "first_page": "1090",
    },
    {
        "label": "open-access, should resolve everywhere",
        "title": "Attenuated multi-mutated herpes simplex virus-1 for the treatment of malignant gliomas",
        "first_author": "Mineta",
        "year": 1995,
        "journal": "Nat Med",
    },
    {
        "label": "TEXTBOOK CHAPTER — must NOT be reported as not-found",
        "title": "Infections with herpes simplex virus",
        "first_author": "Lerner",
        "year": 1983,
        "journal": "Harrison's Principles of Internal Medicine",
        "type": "chapter",
    },
    {
        "label": "DELIBERATELY FABRICATED — the true-positive case",
        "title": (
            "Quantum entanglement of herpesvirus capsids under cryogenic "
            "microfluidic confinement"
        ),
        "first_author": "Nobodysson",
        "year": 2021,
        "journal": "Journal of Implausible Virology",
    },
]


def _summarise(resp: IndexResponse) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "index": resp.index,
        "responded": resp.responded,
        "error": resp.error,
        "n_records": len(resp.records),
    }
    if resp.records:
        r = resp.records[0]
        out["top"] = {
            "title": (r.title or "")[:90],
            "authors": r.authors[:3],
            "year": r.year,
            "doi": r.doi,
            "pmid": r.pmid,
            "container": r.container,
            "type": r.work_type,
            "is_retracted": r.is_retracted,
        }
        out["raw_keys"] = sorted(r.raw.keys())[:25]
    return out


def probe(idx: BibliographicIndexes, spec: Dict[str, Any]) -> Dict[str, Any]:
    query = " ".join(
        str(spec[k]) for k in ("title", "first_author", "year") if spec.get(k)
    )
    results: List[Dict[str, Any]] = []

    if spec.get("doi"):
        results.append(_summarise(idx.crossref_by_doi(spec["doi"])))
        results.append(_summarise(idx.openalex_by_doi(spec["doi"])))
    results.append(_summarise(idx.crossref_bibliographic(query)))
    results.append(_summarise(idx.openalex_by_title(spec["title"])))
    results.append(_summarise(idx.europepmc(query)))
    if all(spec.get(k) for k in ("journal", "year", "volume", "first_page")):
        results.append(_summarise(idx.pubmed_ecitmatch(
            journal=spec["journal"], year=spec["year"], volume=spec["volume"],
            first_page=spec["first_page"], author=spec.get("first_author", ""),
            key="probe",
        )))
    else:
        results.append(_summarise(idx.pubmed_esearch(f"{spec['title']}[Title]")))
    results.append(_summarise(idx.datacite(query)))

    return {"probe": spec["label"], "query": query, "indexes": results}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = ap.parse_args()

    idx = BibliographicIndexes()
    report = [probe(idx, spec) for spec in PROBES]

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return

    for entry in report:
        print(f"\n{'=' * 78}\n{entry['probe']}\n  query: {entry['query'][:90]}")
        for r in entry["indexes"]:
            status = "ok " if r["responded"] else "DOWN"
            line = f"  [{status}] {r['index']:<10} records={r['n_records']}"
            if r.get("error"):
                line += f"  error={r['error'][:60]}"
            print(line)
            if r.get("top"):
                t = r["top"]
                print(f"        title:  {t['title']}")
                print(f"        author: {t['authors']}  year: {t['year']}  doi: {t['doi']}")
                print(f"        type:   {t['type']}  retracted: {t['is_retracted']}")

    print(f"\n{'=' * 78}")
    print("What to check in the output above:")
    print("  1. The textbook chapter should return NO convincing match — and the")
    print("     verifier must classify that as 'unindexed by design', not a finding.")
    print("  2. The fabricated title should return no match from any index.")
    print("  3. Every 'DOWN' line is a field-extraction path to re-verify in")
    print("     index_clients.py before trusting the audit.")


if __name__ == "__main__":
    main()
