# Documentation

Project documentation (non-code, cross-module). [`../CLAUDE.md`](../CLAUDE.md) is the most
complete technical reference; the module READMEs cover each package.

## Guides

- `QUICKSTART.md`: install, run, output formats, configuration, troubleshooting.
- `testing.md`: test layout, markers, offline API fixtures, the opt-in live suite.

## Strategy and plans

| Document | What it is | Status |
|---|---|---|
| `VALUE_PROPOSITION.md` | Who ASV is for, competitor landscape, and the tiered plan (§7) every other plan descends from | Strategy memo, 2026-09-11. Its measurements describe the system as of that date |
| `TIER0_PLAN.md` | VP Tier 0: verdict ontology, plausibility path removed, content gate, evidence invariant, gold set, bibliography audit | **Implemented**, except the gold set (tooling only, zero labels) and gate calibration. §14.5 has the latest full-run numbers |
| `SOURCE_ACQUISITION.md` | VP Tier 1: measured failure analysis of acquisition, and the fix plan | **Phases 0–4 implemented.** §11 has the full-run measurement and per-service credential status |
| `FRONTEND_PLAN.md` | Web UI + API design spec; code cites it by § number, so the numbering is stable | **Implemented**, used as the reference |
| `CITATION_ATTRIBUTION_PLAN.md` | VP Tier 1.7: measured root causes of claim→citation mapping failure, and a 10-task fix plan | **Planned** 2026-11-01; not started |
| `NOTEBOOK_SANDBOX_PLAN.md` | Sandbox the LLM-written analysis scripts; store them as notebooks | **Not started.** N1 recommended; N2–N6 on hold (see below) |
| `RESTRUCTURE.md` | Rationale for the `src/asv` + `apps/` layout | **Implemented** 2026-08-31; historical |

## Progress against VALUE_PROPOSITION §7 (as of 2026-11-01)

✅ done · 🟡 partial · ❌ not started

| # | Item | Status |
|---|---|---|
| **Tier 0** | *Stop producing unearned confidence* | |
| 0.1 | Delete the plausibility verdict | ✅ |
| 0.2 | Verdict ontology | ✅ |
| 0.3 | Content-quality gate | 🟡 built; thresholds uncalibrated |
| 0.4 | Gold set + published false-accusation rate | 🟡 tooling only; **zero pairs labelled** |
| 0.5 | No verdict without a verified quote + URL | ✅ |
| 0.6 | Reference existence + retraction | ✅ 240/253 verified on the reference paper |
| **Tier 1** | *Source acquisition* | |
| 1.1 | Union-then-rank resolution | ✅ |
| 1.2 | Europe PMC, PMC, OpenAlex, DataCite, bioRxiv, DOAJ | 🟡 first four done; **OpenAlex now needs an API key ASV doesn't send**; bioRxiv/DOAJ not added |
| 1.3 | Publisher TDM keys | 🟡 code done; no keys obtained |
| 1.4 | HTTP cache, retry, per-host rate limit | ✅ |
| 1.5 | Login on resolved hosts; persist `storage_state` | 🟡 trigger fixed; not persisted; EZproxy never had a session in a run |
| 1.6 | Citation-kind classification | 🟡 used by the audit; acquisition doesn't skip book chapters |
| 1.7 | **Fix citation attribution** | ❌ planned in `CITATION_ATTRIBUTION_PLAN.md`. Main causes: the marker parser drops multi-reference markers (65 of 123), and there is no paragraph-level citation scope |
| **Tier 2** | *Judgment quality* | |
| 2.1 | Hybrid retrieval, section-aware chunks | ❌ still TF-IDF |
| 2.2 | Structured numeric verification | ❌ |
| 2.3 | Second-opinion adjudication | ❌ |
| 2.4 | Retrieval failure ≠ claim failure | ✅ `retrieval_empty` |
| 2.5 | M1–M6 miscitation detectors | ❌ taxonomy exists only as gold-set labels |
| **Tier 3** | *Product shape* | |
| 3.1 | Triage ranking | ❌ |
| 3.2 | Workflow outputs (memo, annotated PDF) | ❌ web UI only |
| 3.3 | Integrations | ❌ |
| 3.4 | Per-run cost; fix flat token pricing | ❌ |
| 3.5 | Tests for orchestrator/validator/sourcefinder | ✅ 476 tests |
| **Tier 4** | *Cuts* | |
| — | LLM-written scripts, unsandboxed | ❌ still running, still unsandboxed |
| — | DatasetFinder over data.gov + Kaggle | ✅ retargeted to Zenodo/Figshare/DataCite/HF; data.gov off |
| — | Google Scholar scraping | ✅ off by default |
| — | Google Fact Check | ✅ deleted |
| — | `INSTITUTIONAL_COOKIES` as primary path | ✅ demoted to escape hatch |

### Are the plans still aligned?

- **TIER0_PLAN and SOURCE_ACQUISITION are aligned.** They implement Tiers 0 and 1, which
  VP calls the credibility floor and the moat. Their open items are still valid: gold set,
  calibration, `storage_state`, book chapters, the rescue lane. Add the OpenAlex key.
- **NOTEBOOK_SANDBOX_PLAN is only partly aligned.** VP Tier 4 says to replace LLM-written
  scripts with deterministic checks. The plan argues its notebook layer survives that swap,
  which is fair, but N2–N6 (notebook storage, Pyodide re-run, revisions) is a large
  investment in a path that produced zero verdicts in the last full run. N1 (scrub the
  environment, cut network access, move the working directory out of the run folder) is
  cheap and fixes a live security issue. Do N1; hold N2–N6.
- **The highest-leverage VP item is Tier 1.7, citation attribution**, now planned in
  `CITATION_ATTRIBUTION_PLAN.md`. In the 2026-09-23 full run, 214 of 314 claims (68%)
  reached the orchestrator with no citation and became `not_checkable(no_source_available)`.
  No acquisition gain reaches those claims. The plan's measurements correct VP §2.5's
  diagnosis: the LLM finds markers fine (92% recall, no wrong numbers). The losses come
  from the marker parser, the reference parser, and having no paragraph-level citation scope.
- **Tiers 2–3 have no plan docs** beyond VP itself. That is correct sequencing: VP §8 says
  the false-accusation rate decides whether ASV is a product, and it can't be measured
  until the gold set has labels.

**Suggested order:** (1) citation attribution (1.7), (2) the missing credentials, the
OpenAlex key and a working EZproxy session (SOURCE_ACQUISITION §11), (3) label the gold set
and calibrate the gate, (4) sandbox N1. Then Tier 2.

## Module docs

- `../src/asv/extraction/README.md`
- `../src/asv/orchestrator/README.md`
- `../src/asv/validator/README.md`
- `../src/asv/sourcefinder/README.md`
- `../scripts/README.md`
