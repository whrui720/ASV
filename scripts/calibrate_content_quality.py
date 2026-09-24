"""Calibrate the Tier 0.3 content-quality classifier against hand labels.

TIER0_PLAN.md §4.5. The thresholds in ``sourcefinder/config.py`` are starting
points, and they must not ship as guesses: the unsafe direction (an abstract
classified as full text) produces a confident verdict off a page that never had
the answer.

The awkward part is that the evidence is already gone — ``ASV_KEEP_SOURCES`` is
off by default, so ``runs/*/text_sources/`` holds only ``_manifest.json``. So
this script re-fetches the URLs those manifests recorded, politely and into a
local cache, and emits a CSV for hand-labelling.

Workflow::

    # 1. Re-fetch and classify everything the runs ever tried
    python scripts/calibrate_content_quality.py

    # 2. Open calibration/content_quality.csv, fill in the `true_label` column
    #    (full_text | abstract_only | paywall_interstitial | rejected), save as
    #    calibration/content_quality.labels.csv

    # 3. Score the classifier against your labels
    python scripts/calibrate_content_quality.py --score

Also set ASV_KEEP_SOURCES=1 for development runs from here on, so the next
calibration does not need a re-fetch at all.
"""

import argparse
import csv
import hashlib
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import requests  # noqa: E402

from asv.core.run_paths import RUNS_ROOT_DIR  # noqa: E402
from asv.core.verdicts import ContentQuality  # noqa: E402
from asv.sourcefinder.content_quality import assess_content  # noqa: E402
from asv.sourcefinder.text_downloader import TextDownloader  # noqa: E402

CALIBRATION_DIR = _ROOT / "calibration"
CACHE_DIR = CALIBRATION_DIR / "cache"
CSV_PATH = CALIBRATION_DIR / "content_quality.csv"
LABELS_PATH = CALIBRATION_DIR / "content_quality.labels.csv"

PER_HOST_DELAY = 2.0  # be markedly politer than the pipeline; this is a bulk re-fetch


def collect_urls() -> List[Dict[str, str]]:
    """Every URL any run ever tried, deduplicated, with its citation context."""
    seen: Dict[str, Dict[str, str]] = {}
    root = Path(RUNS_ROOT_DIR)
    if not root.is_dir():
        return []
    for manifest_path in sorted(root.glob("*/text_sources/_manifest.json")):
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        for entry in data.get("entries", []):
            for attempt in entry.get("resolution_attempts", []):
                url = attempt.get("url")
                if not url or url in seen:
                    continue
                seen[url] = {
                    "url": url,
                    "run": manifest_path.parent.parent.name,
                    "citation_id": str(entry.get("citation_id", "")),
                    "was_downloaded": str(bool(attempt.get("downloaded"))),
                }
    return list(seen.values())


def fetch(url: str, last_hit: Dict[str, float]) -> Optional[bytes]:
    """Fetch with an on-disk cache and a per-host delay, so re-runs are free."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(url.encode("utf-8")).hexdigest()
    cached = CACHE_DIR / f"{key}.bin"
    if cached.exists():
        return cached.read_bytes()

    host = urlparse(url).netloc
    wait = PER_HOST_DELAY - (time.monotonic() - last_hit.get(host, 0.0))
    if wait > 0:
        time.sleep(wait)
    last_hit[host] = time.monotonic()

    try:
        resp = requests.get(
            url, timeout=45,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "application/pdf,text/html;q=0.9,*/*;q=0.8",
            },
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"    fetch failed: {str(e)[:80]}")
        return None
    cached.write_bytes(resp.content)
    return resp.content


def build() -> None:
    urls = collect_urls()
    if not urls:
        print("No run manifests found under runs/ — nothing to calibrate against.")
        return
    print(f"{len(urls)} distinct URLs across all runs. Re-fetching (cached)…")

    CALIBRATION_DIR.mkdir(parents=True, exist_ok=True)
    downloader = TextDownloader(output_dir=str(CACHE_DIR / "_extract"))
    last_hit: Dict[str, float] = {}
    rows = []

    for i, item in enumerate(urls, 1):
        url = item["url"]
        print(f"  [{i}/{len(urls)}] {url[:88]}")
        body = fetch(url, last_hit)
        if body is None:
            rows.append({**item, "host": urlparse(url).netloc,
                         "predicted": "unfetchable", "true_label": ""})
            continue
        result = downloader._process_bytes(body, url, f"cal{i}")
        signals = result.get("content_signals") or {}
        quality = result.get("content_quality")
        rows.append({
            **item,
            "host": urlparse(url).netloc,
            "format": result.get("format") or "",
            "usable_chars": signals.get("usable_chars", 0),
            "imrad_count": signals.get("imrad_count", 0),
            "imrad_sections": "|".join(signals.get("imrad_sections", [])),
            "ref_line_fraction": signals.get("reference_line_fraction", 0),
            "paywall_hits": "|".join(signals.get("paywall_phrases", [])),
            "page_count": signals.get("page_count") or "",
            "predicted": quality.value if quality else "",
            "true_label": "",
        })

    fields = [
        "url", "run", "citation_id", "was_downloaded", "host", "format",
        "usable_chars", "imrad_count", "imrad_sections", "ref_line_fraction",
        "paywall_hits", "page_count", "predicted", "true_label",
    ]
    with open(CSV_PATH, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    print(f"\nWrote {CSV_PATH} ({len(rows)} rows).")
    print(Counter(r.get("predicted") for r in rows))
    print(
        "\nNext: fill in `true_label` for each row (full_text | abstract_only |\n"
        f"paywall_interstitial | rejected), save as {LABELS_PATH.name}, then run\n"
        "  python scripts/calibrate_content_quality.py --score"
    )


def score() -> None:
    if not LABELS_PATH.exists():
        print(f"No hand labels at {LABELS_PATH}. See --help for the workflow.")
        sys.exit(1)

    with open(LABELS_PATH, encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r.get("true_label")]
    if not rows:
        print("No rows carry a true_label yet.")
        sys.exit(1)

    confusion: Counter = Counter()
    unsafe: List[Dict[str, str]] = []
    safe_misses = 0
    for r in rows:
        pred, true = r["predicted"], r["true_label"].strip()
        confusion[(true, pred)] += 1
        if pred == ContentQuality.FULL_TEXT.value and true != ContentQuality.FULL_TEXT.value:
            unsafe.append(r)
        elif true == ContentQuality.FULL_TEXT.value and pred != ContentQuality.FULL_TEXT.value:
            safe_misses += 1

    total = len(rows)
    correct = sum(n for (t, p), n in confusion.items() if t == p)
    full_text_true = sum(1 for r in rows if r["true_label"].strip() == "full_text")

    print(f"Labelled rows: {total}   exact agreement: {correct}/{total} "
          f"({correct / total:.0%})\n")
    print("true \\ predicted")
    labels = sorted({r["true_label"].strip() for r in rows} | {r["predicted"] for r in rows})
    print("                    " + "".join(f"{p[:11]:>13}" for p in labels))
    for t in labels:
        print(f"{t:<20}" + "".join(f"{confusion[(t, p)]:>13}" for p in labels))

    print(f"\nUNSAFE (not full text -> classified full_text): {len(unsafe)}")
    for r in unsafe[:10]:
        print(f"  {r['true_label']:<20} {r['url'][:80]}")
    print(f"SAFE   (full text -> abstained on): {safe_misses}"
          + (f" of {full_text_true} ({safe_misses / full_text_true:.0%})" if full_text_true else ""))

    print("\nGate: unsafe must be 0; safe misses should stay under ~15%.")
    if unsafe:
        print("FAIL — raise CQ_FULL_TEXT_MIN_CHARS or tighten the IMRaD test.")
        sys.exit(1)
    print("PASS")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--score", action="store_true",
                    help="score the classifier against hand labels instead of re-fetching")
    args = ap.parse_args()
    score() if args.score else build()


if __name__ == "__main__":
    main()
