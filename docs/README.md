# Documentation

Project documentation (non-code, cross-module).

- `QUICKSTART.md` — install and run your first pipeline.
- `testing.md` — how to install test deps and run the suite.
- `FRONTEND_PLAN.md` — design spec for the web UI + API (`web/`, `api/`). Referenced by
  section number from code comments, so its section numbering is stable.
- `RESTRUCTURE.md` — proposed repo reorganization (packaging, layout, doc consolidation).
- `SOURCE_ACQUISITION.md` — measured failure analysis of the text/dataset acquisition layer.
- `VALUE_PROPOSITION.md` — who ASV is for, what works and what doesn't, competitor
  landscape, and a sequenced plan to make it viable.
- `TIER0_PLAN.md` — the implementation plan for Tier 0 of that sequence: the
  verdict ontology, the removal of the plausibility path, the content-quality
  gate, the evidence invariant, the gold set, and reference-existence checking.
  **Implemented** — see its status header for what landed and where it deviated.
- `NOTEBOOK_SANDBOX_PLAN.md` — plan for sandboxing the LLM-generated data-analysis
  scripts and persisting them as Jupyter notebooks that the web UI renders and
  re-runs in the browser. **Proposed.**

## Module docs

- `../src/asv/extraction/README.md`
- `../src/asv/orchestrator/README.md`
- `../src/asv/validator/README.md`
- `../src/asv/sourcefinder/README.md`
