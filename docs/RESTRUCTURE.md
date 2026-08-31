# ASV Repository Restructure Proposal

Status: **IMPLEMENTED** (2026-08-31). The low-risk cleanup and the full `src/asv` +
`apps/` migration described below have both landed; the test suite passes with the
same results as before the move (no regressions). This document is kept as the
rationale/reference for the layout. Sections describing the "before" state and the
step order are historical.
Date: 2026-08-31.

---

## TL;DR

- **Stay one repository.** The four pipeline stages share data models and the run-folder
  convention and import each other directly; separate repos would cut a version boundary
  through tightly-coupled code. See [§1](#1-one-repo-or-several).
- **Collapse the flat top-level into a single installable `asv` package** with a real
  `pyproject.toml`, so imports stop depending on "the repo root happens to be on `sys.path`".
- **Split deployables from the library**: `apps/api` (FastAPI) and `apps/web` (React) are
  *applications*; the pipeline is a *package* they both consume.
- **Consolidate the docs.** There are ~13 tracked Markdown files with heavy overlap and at
  least one that's now stale (`FRONTEND_PLAN.md` says "not yet implemented" — it is).
- **Delete the junk** currently tracked in git (`=1.40.0`, stray caches).

---

## 1. One repo, or several?

**Recommendation: one repo (monorepo).**

Why not split each Python module into its own repo:

- `orchestrator/claim_orchestrator.py` imports `validator`, `sourcefinder`, and
  `hybrid_citation_scraper` directly (7+ cross-package imports). These are not
  independently versioned libraries — they're stages of one pipeline.
- Every module depends on the root-level `models.py` (the `ClaimObject` / `ValidationResult`
  Pydantic contracts) and `run_paths.py` (the run-folder layout). A change to a model would
  require a coordinated release across N repos. That's pure overhead for a solo/small project.
- There is no external consumer importing these packages à la carte. The unit of delivery is
  "run the pipeline," not "install `asv-validator` from PyPI."

The **only** boundary that could ever justify a second repo is **web frontend vs Python
backend** — different languages, toolchains, deploy targets. But they're coupled through the
OpenAPI contract (`web/` runs `openapi-typescript` against the live API to generate its types)
and are built together. Keep them in one repo under `apps/`; revisit only if the frontend gets
its own team or release cadence.

> Reconsider a split **only** if: a stage gets reused by an unrelated project, or the web app
> needs an independent deploy pipeline and separate contributors. Neither is true today.

---

## 2. Current problems

| # | Problem | Evidence |
|---|---------|----------|
| 1 | **No package namespace.** Shared modules float at repo root and are imported as bare top-level names (`from models import …`, `from run_paths import …`). Only works because CWD is on `sys.path`. | `models.py`, `llm_config.py`, `run_paths.py`, `run_events.py`, `interaction.py` at root |
| 2 | **Flat sibling packages.** Five packages + `scripts/` all at top level with no grouping of "library" vs "app". | `hybrid_citation_scraper/`, `orchestrator/`, `validator/`, `sourcefinder/`, `api/` |
| 3 | **No `pyproject.toml`.** Dependencies split across two `requirements.txt` files (root + `hybrid_citation_scraper/`) that overlap and disagree. Root file has no trailing newline (`…0.0.9` runs into the next). | `requirements.txt`, `hybrid_citation_scraper/requirements.txt` |
| 4 | **Junk tracked in git.** A pip build log committed as a filename. | `=1.40.0` (tracked), `.coverage`, `__pycache__/` present |
| 5 | **Doc sprawl + staleness.** ~13 Markdown files with overlapping install/usage content; `FRONTEND_PLAN.md` describes the web UI as "proposal / not yet implemented" though `web/` and `api/` now exist. | root `README.md`, `QUICKSTART.md`, `CLAUDE.md`, `docs/README.md`, `docs/FRONTEND_PLAN.md`, `docs/testing/*` (4), 5 per-module READMEs |
| 6 | **Historical module name.** `hybrid_citation_scraper` is really "Stage 1: claim extraction" — the name predates the current architecture. | CLAUDE.md calls it "Stage 1: Claim Extraction" |
| 7 | **pytest config is stage-1-centric.** `--cov=hybrid_citation_scraper` only, though `api/tests` is in `testpaths`. | `pytest.ini` |

---

## 3. Target structure

```
asv/                                  # repo root
├── pyproject.toml                    # single source of deps + build config (replaces both requirements.txt)
├── README.md                         # short: what it is, quickstart link, architecture link
├── CLAUDE.md                         # stays (agent instructions)
├── .env.example                      # committed template (real .env stays gitignored)
│
├── src/
│   └── asv/                          # ONE installable package — imports become `from asv.core.models import …`
│       ├── __init__.py
│       ├── core/                     # shared contracts + run plumbing (was: root-level loose files)
│       │   ├── models.py             # ← models.py
│       │   ├── run_paths.py          # ← run_paths.py
│       │   ├── run_events.py         # ← run_events.py
│       │   ├── interaction.py        # ← interaction.py
│       │   └── llm_config.py         # ← llm_config.py
│       ├── extraction/               # ← hybrid_citation_scraper/  (renamed; Stage 1)
│       │   ├── claim_extractor.py
│       │   ├── llm_client.py
│       │   ├── config.py
│       │   └── utils.py
│       ├── sourcefinder/             # ← sourcefinder/  (Stage 3 utilities)
│       ├── validator/                # ← validator/
│       └── orchestrator/             # ← orchestrator/   (Stage 2)
│
├── apps/
│   ├── api/                          # ← api/   FastAPI service (a deployable, not library code)
│   │   ├── main.py, deps.py, schemas.py
│   │   ├── routers/  services/
│   │   └── tests/
│   └── web/                          # ← web/   React + Vite frontend
│       └── src/ …                    # (node_modules/, dist/ stay gitignored)
│
├── scripts/                          # thin CLI entry points (or migrate to pyproject [project.scripts])
│   ├── run_pipeline.py
│   ├── run_orchestrator.py
│   ├── run_webapp.py
│   └── revalidate_citation.py
│
├── tests/                            # OR keep tests co-located per package — pick one, see §4
│
├── docs/
│   ├── ARCHITECTURE.md               # the canonical deep-dive (absorbs the big README body + CLAUDE.md prose)
│   ├── QUICKSTART.md                 # install + first run only
│   ├── testing.md                    # ← merge docs/testing/* (4 files → 1)
│   └── frontend.md                   # ← FRONTEND_PLAN.md, rewritten to describe what EXISTS
│
├── pdfs/        (gitignored — inputs)
└── runs/        (gitignored — outputs)
```

### Why this shape

- **`src/asv/` layout** — the standard "src layout." Forces you to install the package
  (`pip install -e .`) rather than relying on CWD, which makes imports unambiguous and tests
  run the *installed* code. All the fragile `from models import` become `from asv.core.models import`.
- **`core/`** gives the shared contracts a home so it's obvious what every stage depends on.
- **`apps/` vs `src/`** encodes the real distinction: `api` and `web` are things you *deploy*;
  the pipeline is a thing you *import*. The API imports `asv`; it doesn't live inside it.
- **Rename `hybrid_citation_scraper` → `extraction`** to match the architecture vocabulary
  ("Stage 1: Claim Extraction"). This is the highest-churn rename — do it in its own commit.

---

## 4. Migration plan (incremental, low-risk order)

Each step is a self-contained commit that leaves the repo runnable.

1. **Cleanup (no code change).**
   - `git rm --cached '=1.40.0' .coverage` and delete `=1.40.0`; ensure `.coverage`,
     `__pycache__/`, `.venv/` are gitignored (mostly already are).
   - Add `.env.example`.

2. **Adopt `pyproject.toml`.** Merge both `requirements.txt` into `[project.dependencies]`
   (pin what the root file pins). Keep a generated `requirements.txt` only if a deploy target
   needs it. Delete `hybrid_citation_scraper/requirements.txt`.

3. **Introduce `src/asv/` and move `core/`.** Move the five loose root modules into
   `src/asv/core/`. Update imports (`from models` → `from asv.core.models`). This touches the
   most files but is mechanical — do it with a scripted find/replace and run the tests.

4. **Move the four packages under `src/asv/`** (`sourcefinder`, `validator`, `orchestrator`,
   and `extraction`←`hybrid_citation_scraper`). Rename in the same step; update imports.

5. **Move `api/` → `apps/api/`, `web/` → `apps/web/`.** Update `pytest.ini` `testpaths` and
   the `--cov` target (`--cov=asv` now). Point `run_webapp.py` at the new api path.

6. **Consolidate docs** (see §5). Do this last so links point at the settled tree.

> Decision to make in step 3/4: **co-located tests vs a top-level `tests/`.** Current code
> co-locates (`hybrid_citation_scraper/tests/`, `api/tests/`). Co-located is fine and less
> disruptive — keep it. A single top-level `tests/` is only worth it if you want one obvious
> place for cross-stage integration tests. Recommend: keep unit tests co-located, add a small
> top-level `tests/integration/` for end-to-end pipeline tests.

---

## 5. Documentation consolidation

Target: **one canonical doc per audience**, no duplicated install instructions.

| Keep | Role | Absorbs / replaces |
|------|------|--------------------|
| `README.md` (root, short) | Front door: one-paragraph pitch, quickstart link, architecture link, repo map | trims the current 20 KB README |
| `docs/QUICKSTART.md` | Install + first `run_pipeline` + env vars | current `QUICKSTART.md` (mostly fine) |
| `docs/ARCHITECTURE.md` | The 3-stage deep dive, run-folder layout, routing logic | body of current `README.md` + the architecture prose duplicated in `CLAUDE.md` |
| `docs/testing.md` | How to run/write tests | **merge** `docs/testing/`'s 4 files |
| `docs/frontend.md` | What the web UI + API actually do | **rewrite** `FRONTEND_PLAN.md` (drop "not yet implemented") |
| `CLAUDE.md` | Agent instructions only | keep; point it at `docs/ARCHITECTURE.md` instead of restating it |
| per-package `README.md` (×5) | Optional 5–10 line "what this package does" | trim to a pointer + keep only if it adds signal beyond docstrings |

To delete after merging: `docs/testing/INSTALLATION_AND_USAGE.md`,
`docs/testing/TESTING_GUIDE.md`, `docs/testing/TEST_SUITE_SUMMARY.md`,
`docs/testing/README.md`, `docs/README.md` (its index role moves to root README).

Note: `runs/hsv_cancer__20260622_001554/logs/observed_issues.md` is a run artifact, not docs —
it lives under gitignored `runs/` and needs no action.

---

## 6. What NOT to change

- The **run-folder layout** (`runs/{stem}__{timestamp}/…`) is well-designed and documented —
  leave it exactly as is. Only its owner module moves (`run_paths.py` → `asv.core.run_paths`).
- The **4-group claim routing** and orchestrator logic — architecture is sound; this is purely
  a packaging/naming reorg, not a redesign.
- **Gitignore of `pdfs/` and `runs/`** — correct; keep.

---

## 7. Rough effort

| Step | Effort | Risk |
|------|--------|------|
| 1 Cleanup | 15 min | none |
| 2 pyproject | 30 min | low |
| 3 core/ move | 1–2 hr | medium (import churn — scripted) |
| 4 package moves + rename | 1–2 hr | medium |
| 5 apps/ move | 30 min | low |
| 6 docs | 1–2 hr | none |

Total ≈ a focused afternoon. Steps 1–2 and 6 deliver value even if you never do the package
moves, so they're safe to land first.
