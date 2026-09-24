# Notebooks + Sandboxing — Implementation Plan

**Status:** proposed (written 2026-09-19, from `main` at `bbb7be1` + uncommitted Tier 0 work).
**Scope:** turn the LLM-generated data-analysis scripts into (a) sandboxed executions and
(b) Jupyter notebooks that are stored per run and rendered — and re-runnable — in the web UI.

Companion documents: [`VALUE_PROPOSITION.md`](VALUE_PROPOSITION.md) §2.4(c), §7 Tier 4 (this
path is slated for replacement — see §12), [`TIER0_PLAN.md`](TIER0_PLAN.md) §5 (the evidence
invariant this plugs into), [`FRONTEND_PLAN.md`](FRONTEND_PLAN.md) (the UI this extends).

---

## 1. What exists today

**Yes, the scripts are saved.** `PythonScriptValidator` writes every generated script to
`runs/{run}/generated_scripts/validate_{claim_id}.py` (`python_script_validator.py:44-47`),
`read_model._script_path_for` finds it, `ClaimDetail.generated_script_source` inlines it, and
`ClaimDetailDrawer.tsx:273` renders it in a read-only `<pre>`. Two run folders have them
(`hsv_cancer__20260703_140140`: 15, `..._162705`: 12).

What is **not** saved, and what is wrong with how they run:

| Gap | Where | Consequence |
|---|---|---|
| Execution record is discarded | `_parse_execution_result` keeps only the parsed JSON; `stdout` before/after the JSON, `stderr`, exit code, and wall time are dropped | The script is on disk but what it *did* is not. A reader cannot tell a clean run from one that printed 40 pandas warnings first |
| The dataset is deleted | `claim_orchestrator.py:821`, unless `ASV_KEEP_SOURCES` | The stored script cannot be re-run by anyone, including us |
| No provenance | Nothing records model, temperature, prompt version, pandas version, dataset URL or hash | The script cannot be tied to the verdict it produced |
| **Full environment inherited** | `subprocess.run(['python', path], ...)` with no `env=` | The generated code runs with `GEMINI_API_KEY`, `KAGGLE_KEY`, `SEMANTIC_SCHOLAR_API_KEY` and everything else `load_dotenv` put in `os.environ` (`core/llm_config.py:10`) |
| **Full network access** | same | LLM-authored code can POST those keys anywhere |
| **Writable run folder** | `cwd=script_path.resolve().parent` — i.e. inside `runs/{run}/generated_scripts/` | Generated code can overwrite the run's own artifacts |
| Unbounded stdout | nothing caps `result.stdout` | `print('x' * 10**9)` OOMs the pipeline process |
| Dead config | `SCRIPT_TIMEOUT`, `SCRIPT_TIMEOUT_SECONDS`, `SCRIPT_MAX_OUTPUT_LENGTH`, `VALIDATION_SCRIPTS_DIR` in `validator/config.py` are imported by nothing; the timeout is hardcoded `30` | Tuning them does nothing |

VALUE_PROPOSITION.md §2.4(c) already documents the failure this enables — a script that invented
`attachment_time_minutes` / `penetration_time_minutes` columns and ran against a CrossRef
bibliographic record. It ran with the project's API keys in its environment.

## 2. The correction to make first: a notebook is not a sandbox

The question "can we sandbox it inside a Jupyter notebook?" has a clean answer: **no, and this
is worth being precise about.** A Jupyter kernel is an ordinary Python process with the ordinary
privileges of whoever started it. `ipykernel` adds a ZMQ message loop, not a boundary — it is
strictly *worse* than the current `subprocess.run` if run in-process, because it is long-lived.

So the two asks are orthogonal and should be built as separate layers:

- **Containment** comes from an OS/VM boundary — a container, a WASM runtime, or a restricted
  OS process. §5.
- **The notebook** is the *artifact of record*: a structured, human-readable, re-runnable
  transcript of what the sandbox did. §4.

Building them as two independent modules matters for a second reason. VALUE_PROPOSITION.md
Tier 4 proposes replacing the LLM script-writer with a whitelisted DSL of deterministic checks.
If the notebook layer is coupled to `PythonScriptValidator`, that replacement throws this work
away. If the notebook layer takes *cells from any producer*, the DSL emits notebooks too — and
a notebook of deterministic recomputation cells is exactly the right output shape for a
statcheck-style check. **The generator must be swappable; the notebook and the sandbox stay.**

## 3. Target architecture

```
                   ┌──────────────────────────────────────┐
  claim + dataset →│ cell producer                        │
                   │  • ScriptGenerator (LLM, today)      │  swappable
                   │  • DeterministicChecks (Tier 4 DSL)  │
                   └──────────────┬───────────────────────┘
                                  │  List[Cell]
                   ┌──────────────▼───────────────────────┐
                   │ NotebookBuilder  (asv/validator/     │
                   │   notebook.py) — nbformat v4 +       │
                   │   provenance metadata block          │
                   └──────────────┬───────────────────────┘
                                  │  nbformat.NotebookNode
                   ┌──────────────▼───────────────────────┐
                   │ SandboxExecutor  (asv/validator/     │
                   │   sandbox/) — executes cell by cell, │
                   │   attaches outputs, enforces limits  │
                   │   tiers: subprocess | wasm | docker  │
                   └──────────────┬───────────────────────┘
                                  │  executed notebook + ExecutionRecord
        ┌─────────────────────────┼──────────────────────────────┐
        ▼                         ▼                              ▼
  runs/*/notebooks/       ValidationResult              API → React
  validate_{id}.ipynb     (verdict + EvidenceSpan       NotebookViewer (read-only)
  + data/ sidecar          locator → cell index)        NotebookRunner (Pyodide, in-browser)
```

## 4. The notebook of record

### 4.1 Generating cells

Change the prompt in `_build_script_generation_prompt` to ask for **percent-format** output —
`# %%` for a code cell, `# %% [markdown]` for prose:

```python
# %% [markdown]
# ## Claim
# "Median household income rose 4.2% between 2019 and 2021."
# %%
import pandas as pd
df = pd.read_csv(ASV_DATASET)
df.columns.tolist()
# %%
...
```

Rationale for percent format over asking for structured JSON cells: models emit it reliably
(it is the jupytext convention, heavily represented in training data), it survives the existing
triple-backtick fence stripping in `_extract_code` unchanged, and **degradation is graceful** —
a model that ignores the markers produces a valid one-cell notebook rather than a parse failure.
A JSON cell schema adds a new failure mode to a path that already has too many.

`notebook.split_percent_cells(source) -> List[Cell]` is a ~30-line deterministic splitter, unit
tested against: no markers, markers only at the top, trailing empty cell, `# %%` inside a string
literal (split on line-start markers only).

The prompt also changes in two substantive ways:

- The dataset path is no longer interpolated as a literal. The builder injects
  `ASV_DATASET` (a `pathlib.Path`) into the first cell; the prompt instructs the model to use it.
  This is what makes the same notebook run in the sandbox, on a reviewer's laptop, and in the
  browser.
- The final cell must `print(json.dumps({...}))` exactly as today, so `_parse_execution_result`
  is unchanged.

### 4.2 Structure and provenance

`NotebookBuilder.build(claim, dataset, cells, provenance) -> NotebookNode`:

| Cell | Content |
|---|---|
| 0 (markdown) | Claim text, `claim_id`, citation marker + raw reference string, verdict slot (filled post-execution), and the dataset header from §4.3 |
| 1 (code) | Preamble: `import json, pathlib; ASV_DATASET = pathlib.Path("data/<filename>")` |
| 2..n-1 | The generated cells |
| n (code) | The `json.dumps` verdict emission, if the model did not already end with one |

Provenance goes in `nb.metadata["asv"]` (nbformat permits arbitrary metadata keys) so it travels
with a downloaded `.ipynb`:

```jsonc
{
  "schema_version": 1,
  "run_id": "hsv_cancer__20260703_140140",
  "claim_id": "claim_2_5",
  "citation_id": "12",
  "generator": {"kind": "llm_script", "model": "gemini-2.5-pro",
                "temperature": 0.2, "prompt_version": "2026-09-19.notebooks"},
  "dataset": {"url": "...", "sha256": "...", "bytes": 184320, "format": "csv",
              "retention": "full" | "sample" | "absent", "sample_rows": null},
  "execution": {"tier": "wasm", "started_at": "...", "wall_ms": 4130,
                "exit": "ok" | "error" | "timeout" | "output_truncated",
                "runtime": {"python": "3.11.3", "pandas": "2.2.0",
                            "pyodide": "0.26.2"}},
  "verdict": {"passed": true, "confidence": 0.9, "explanation": "..."}
}
```

`execution.runtime` is the versions **inside the sandbox**, not the pipeline's. Once execution
moves into a pinned sandbox, the host's `pandas==2.3.3` stops being the number that matters,
and recording the wrong one would be worse than recording none.

### 4.3 Keeping the data the notebook needs

The orchestrator deletes datasets after each batch (`claim_orchestrator.py:821`). A notebook
nobody can re-run is a decoration, so the notebook keeps its **own** capped copy under
`runs/{run}/notebooks/data/`, written before the batch cleanup and exempt from it.

| Dataset size | Retention | Notebook header says |
|---|---|---|
| ≤ `NOTEBOOK_DATA_MAX_MB` (default 25) | `full` — byte-for-byte copy | "Re-runnable. sha256 `abc…`" |
| > cap, tabular | `sample` — first `NOTEBOOK_DATA_SAMPLE_ROWS` (default 5000) rows, schema preserved | "**This is a 5,000-row sample of a 412 MB file.** The verdict below was computed on the full file (sha256 `abc…`); re-running here may not reproduce it." |
| > cap, non-tabular, or delete raced | `absent` | "The source data was not retained. The recorded outputs are the evidence; the notebook cannot be re-run." |

The header text is generated, not hand-written per case, and the same three states drive a badge
in the UI. Stating "this cannot be reproduced" where true is the same discipline the verdict
ontology applies to abstentions — it is the whole reason that ontology exists.

### 4.4 `RunPaths` changes

```python
notebooks: Path                         # runs/{run}/notebooks/
def notebook_path(self, claim_id: str) -> Path:         # notebooks/validate_{id}.ipynb
def notebook_data_dir(self) -> Path:                    # notebooks/data/
def notebook_revisions_dir(self, claim_id: str) -> Path # notebooks/revisions/{claim_id}/
```

Added to the frozen dataclass, `_build` and `_ensure` — `from_existing` on the eight legacy run
folders creates the empty dirs, which is harmless and keeps the shape uniform.

`generated_scripts/validate_{id}.py` **keeps being written** (the percent-format source, before
execution). It costs one `write_text`, keeps `git diff`/`grep` working across runs, and means
PR sequencing does not have to break `read_model` and the drawer in the same change.

## 5. The sandbox

### 5.1 What "sandboxed" has to mean here

Non-negotiable, in priority order:

1. **No environment inheritance.** The single highest-value fix, and the one that is cheap
   under every option. `env={}` plus an explicit allowlist (`PATH`, `SYSTEMROOT` on Windows).
2. **No network.** LLM code has no legitimate reason to make a request; the dataset is already
   on disk.
3. **Filesystem confined** to a scratch dir + the dataset, read-only. Specifically *not* the run
   folder.
4. **Wall-clock + memory + output caps**, all enforced, all recorded when they trip.
5. **Cross-platform.** Primary dev machine is Windows 11 with no Docker installed.

### 5.2 Options

| | **A. Hardened subprocess** | **B. Docker** | **C. Pyodide in Playwright (WASM)** |
|---|---|---|---|
| Boundary | Same-OS process, `-I -E -S`, empty env, scratch cwd | Container: `--network none --read-only --cap-drop ALL --memory 512m --pids-limit 64 -u 65534` | WASM + Chromium renderer sandbox; no syscalls at all |
| Env leak | Fixed | Fixed | Fixed (no env exists) |
| Network | Only soft-blocked (`socket` monkeypatch; `ctypes` defeats it) | Fixed at the kernel | **Structurally impossible** — Pyodide has no raw sockets; JS `fetch` blocked by `route("**", abort)` |
| Filesystem | Confined by convention, not enforced | Enforced by mount | In-memory Emscripten FS; host FS unreachable |
| Memory cap | Job Object (Win) / `setrlimit` (POSIX) | `--memory` | V8 heap cap |
| Real Jupyter kernel | No (we drive cells) | **Yes** — `nbclient` + `ipykernel` in-image | No (we drive cells over a JS bridge) |
| New dependency | none | Docker Desktop (~1 GB, not installed) | none new — **Playwright is already a dependency** for the paywall flow; plus a vendored Pyodide build (~30 MB pinned) |
| Package fidelity | Host pandas 2.3.3 | Whatever the image pins | Pyodide's pandas/numpy/scipy/scikit-learn/openpyxl |
| Startup | ~0.2 s | ~1–2 s | ~2–5 s, amortizable by reusing one page per batch |
| Browser parity | None | None | **Exact** — identical runtime to §7's in-browser runner |
| Effort | ~1 day | ~1–2 days + install friction | ~3–4 days |
| Verdict | **Floor.** A mitigation, not a boundary | The conventional answer | **Recommended target** |

### 5.3 Recommendation

**Land A immediately, then build C as the default tier; keep B as an opt-in for anyone who
already runs Docker.**

A is worth landing on its own schedule because the env-inheritance hole is live today and is
fixed by a five-line change — it should not wait behind a notebook renderer.

C is the recommendation for the target because of the third row from the bottom. The reviewer
re-running a cell in the web UI (§7) and the pipeline that produced the verdict execute **the
same pinned Pyodide build**. Any other pairing means the UI can quietly disagree with the
verdict it is displaying, which is precisely the class of defect this codebase spends its
verdict ontology avoiding. Playwright already being installed for the paywall flow removes the
usual objection to C, and vendoring a pinned Pyodide distribution makes package versions fixed
forever — better determinism than either alternative.

C's real costs, stated plainly: we drive cells over a JS bridge instead of getting `nbclient`
for free (~150 lines); pandas-in-WASM is 2–5× slower and a handful of C-extension corners
differ; and the vendored build is a large binary artifact to pin and gitignore.

**Decision point for you:** if you would rather have a real Jupyter kernel and the boring,
conventional boundary, B is the better plan and installing Docker Desktop is the price. Say so
before N3 and the rest of this document is unchanged — every tier implements one interface.

### 5.4 The interface

```python
# src/asv/validator/sandbox/base.py
@dataclass(frozen=True)
class CellResult:
    outputs: list[dict]          # nbformat v4 output structs
    ok: bool
    wall_ms: int
    truncated: bool

@dataclass(frozen=True)
class ExecutionRecord:
    tier: str                    # "subprocess" | "wasm" | "docker"
    exit: str                    # "ok" | "error" | "timeout" | "output_truncated"
    wall_ms: int
    runtime: dict[str, str]
    stdout_tail: str             # capped
    stderr_tail: str

class SandboxExecutor(Protocol):
    def available(self) -> bool: ...
    def execute(self, nb: NotebookNode, dataset: Path | None,
                limits: Limits) -> tuple[NotebookNode, ExecutionRecord]: ...
```

Tier selection: `ASV_SANDBOX_TIER` env var (`auto` default) → first available of
`wasm`, `docker`, `subprocess`. `Limits` comes from `validator/config.py`, where the dead
constants listed in §1 get resurrected and actually wired: `SCRIPT_TIMEOUT_SECONDS=30`,
`SCRIPT_MAX_OUTPUT_LENGTH=10000` (per cell, with `truncated: true` recorded), plus new
`SANDBOX_MEMORY_MB=512`, `SANDBOX_MAX_NOTEBOOK_MB=5`.

### 5.5 The tier is part of the record

`ExecutionRecord.tier` is persisted on `ValidationResult.validation_metadata` and rendered as a
badge. A verdict produced under `subprocess` is not the same epistemic object as one produced
under `wasm`, and the UI should not present them identically — the same argument
`content_quality` makes for text sources.

## 6. API

All read-only or store-only. **There is deliberately no server-side execute endpoint**: the
server never runs code a user edited. Re-execution happens in the user's own browser (§7),
where the browser is the sandbox and the blast radius is their tab.

| Endpoint | Returns |
|---|---|
| `GET /api/runs/{run_id}/claims/{claim_id}/notebook` | The `.ipynb` JSON + `{retention, sandbox_tier, data_url}`; 404 with a reason for legacy runs |
| `GET /api/runs/{run_id}/claims/{claim_id}/notebook/download` | `FileResponse`, `application/x-ipynb+json`, attachment |
| `GET /api/runs/{run_id}/claims/{claim_id}/notebook/data` | The retained dataset bytes, or 404 with `retention: "absent"` |
| `GET /api/runs/{run_id}/claims/{claim_id}/notebook/revisions` | User-saved revisions, newest first |
| `PUT /api/runs/{run_id}/claims/{claim_id}/notebook/revisions` | Stores an edited notebook. Validates with `nbformat.validate`, caps at `SANDBOX_MAX_NOTEBOOK_MB`, **never executes**, **never touches the notebook of record** |

Schema additions (`apps/api/schemas.py`): `ClaimRow.notebook_path`, `ClaimRow.notebook_status`
(`"of_record" | "legacy_script_only" | "none"`), and `NotebookEnvelope` / `NotebookRevision`.
`read_model._script_path_for` gains a sibling `_notebook_path_for`; both are set so the drawer
can prefer the notebook and fall back.

## 7. Frontend

**`NotebookViewer.tsx` (read-only).** Hand-rolled nbformat v4 renderer rather than pulling in
JupyterLab: markdown cells via `marked` + `dompurify`, code cells via `prismjs` (python grammar
only), outputs by type — `stream` → `<pre>`; `execute_result`/`display_data` → `text/html`
(sanitized) ⊃ `image/png` (base64 `<img>`) ⊃ `text/plain`; `error` → traceback with ANSI
stripped, styled as an error. ~200 lines against ~2 MB of JupyterLab dependencies for a viewer
that needs none of its extension system.

Header strip: verdict badge · sandbox tier badge · data-retention badge (§4.3) · model +
prompt version · "Download .ipynb".

**`NotebookRunner.tsx` (interactive).** Pyodide loaded **lazily on first "Run"** — never on
drawer open — into a **Web Worker** so a runaway cell cannot freeze the UI (the worker is
`terminate()`-able, which is the timeout mechanism). The dataset is fetched from
`notebook/data` and written into the Pyodide FS at the path `ASV_DATASET` points to, so cells
are identical to the ones the pipeline ran. Controls: run cell, run all, reset kernel, revert
cell, save revision. Disabled with an explanatory note when `retention: "absent"`.

An edited notebook **never** changes the displayed verdict. Revisions are a scratchpad for a
reviewer asking "what if the column were the other one?" — the verdict of record stays bound to
the notebook of record, and the UI says so.

**Placement.** A notebook does not fit a drawer. Add a `Notebook` tab in `ClaimDetailDrawer`
that shows the header strip, the verdict cell, and an "Open full notebook →" link to a new route
`/runs/:runId/claims/:claimId/notebook` (`routes/NotebookView.tsx`) carrying viewer + runner.

New web deps, all pinned: `marked`, `dompurify`, `prismjs`, `pyodide`.

## 8. Wiring into the verdict

`ProcessQuantitative.validate_claim` changes in three places (`process_quantitative.py`):

- `EvidenceSpan.locator` becomes `notebooks/validate_{claim_id}.ipynb#cell={n}` — the index of
  the cell whose output produced the verdict JSON, not just a file path. The Tier 0 rule is that
  evidence is checkable in ten seconds; a 90-line file plus "it's in there somewhere" is not.
- `validation_metadata` gains `{"notebook_path", "sandbox_tier", "dataset_sha256",
  "dataset_retention", "execution_exit"}`.
- A new abstention: `execution_exit == "timeout"` → `not_checkable(VALIDATION_ERROR)` with the
  timeout stated, rather than today's generic "Script execution failed".

`EvidenceSpan.verified_verbatim=True` stays justified, and is *more* justified: the quoted JSON
is now literally present as a recorded cell output in a stored artifact, produced by a run whose
runtime versions and input hash are recorded.

`run_events`: emit `notebook_executed {claim_id, tier, exit, wall_ms, n_cells}` so
`LiveConsole` shows sandbox activity.

## 9. Backward compatibility

The eight existing run folders are the evidence base for published numbers and are never
rewritten (TIER0_PLAN.md §9). Two of them have `generated_scripts/*.py` and no notebook:
`notebook_status: "legacy_script_only"` → the UI keeps today's read-only `<pre>`, with a note
that the run predates notebooks, and the runner is unavailable. `notebook/*` endpoints 404 with
that reason rather than an empty body.

`nb.metadata.asv.schema_version` starts at 1 so a future change to the metadata block is
detectable on read.

## 10. Tests

| Area | Tests |
|---|---|
| `split_percent_cells` | no markers → 1 cell; leading/trailing markers; markdown markers; `# %%` inside a string; CRLF |
| `NotebookBuilder` | output passes `nbformat.validate`; provenance block complete; `ASV_DATASET` preamble present; verdict cell appended only when missing |
| Dataset retention | full/sample/absent tiering by size; sha256 is of the **original**; sample preserves schema; survives batch cleanup |
| **Sandbox contract** (`-m sandbox`, parametrized over available tiers) | `os.environ.get("GEMINI_API_KEY")` → `None`; `import socket; socket.socket()` / `requests.get` → fails; `open("../../../claims.json","w")` → fails; `while True: pass` → killed at the limit, `exit == "timeout"`; `print("x"*10**9)` → truncated, `truncated: true`, pipeline process survives; writing to scratch → succeeds |
| API | notebook/download/data/revisions happy paths; legacy 404 reason; `PUT` rejects invalid nbformat and oversize; `PUT` does not mutate the notebook of record |
| `read_model` | `notebook_status` for all three states |

The sandbox contract tests are the important ones: they are the only mechanical statement of
what this plan actually promises, and they must be written against the interface so every tier
is held to the same bar. Tiers unavailable on the machine skip rather than fail.

There is no frontend test runner in the repo (no vitest config); the viewer and runner ship
untested unless adding one is in scope — flagging, not assuming.

## 11. Sequencing

| PR | Content | Independently valuable? |
|---|---|---|
| **N0** | Throwaway spike: Pyodide + Playwright runs a pandas cell on Windows; measure startup, correctness vs host pandas on the existing 27 scripts, and the vendored build's real size | Decides §5.3 with numbers |
| **N1** | `SandboxExecutor` interface + subprocess tier + contract tests + wire the dead config constants | **Yes — closes the credential-exfiltration hole regardless of which tier wins.** Land first, independent of everything else |
| **N2** | `notebook.py` (splitter + builder), prompt → percent format, `RunPaths` additions, dataset retention, notebook written and executed via N1's tier | Yes — notebooks on disk, downloadable |
| **N3** | The chosen boundary tier (wasm or docker) behind `ASV_SANDBOX_TIER`; vendor + pin | Yes |
| **N4** | API endpoints + schema additions | No (feeds N5) |
| **N5** | `NotebookViewer` + drawer tab + `NotebookView` route | Yes |
| **N6** | `NotebookRunner` (Pyodide in a worker) + revisions | Yes |

N1 and N2 are the load-bearing ones. If the work stops after N2, the security hole is closed and
every run produces a downloadable, provenance-carrying notebook that opens in any Jupyter —
which is most of the value, without any frontend work.

## 12. Risks

| Risk | Mitigation |
|---|---|
| **Tier 4 deletes this path anyway** (VALUE_PROPOSITION.md §7) | §2's layering is the answer: the DSL becomes another cell producer. The sandbox and notebook survive the swap. If anything this plan makes the Tier 4 cut *easier* — a deterministic check that emits a notebook is strictly more legible than one that emits a number |
| Pyodide pandas ≠ host pandas; a verdict changes | This is a feature once execution moves into the sandbox: the sandbox's version is the one of record and is pinned + recorded. N0 measures the delta on the existing 27 scripts before committing |
| Per-claim startup latency | Reuse one Pyodide page per batch (claims are already batched by `citation_id`); N0 measures |
| Notebooks bloat the run folder | Per-cell output cap + `SANDBOX_MAX_NOTEBOOK_MB`; dataset copies capped at 25 MB, larger ones stored as samples |
| Vendored Pyodide is a large binary | Pinned, gitignored, fetched by a setup script; `available()` returns False and the tier falls back if absent |
| Revisions endpoint becomes an accidental RCE | The endpoint stores JSON and validates it. Nothing server-side ever executes a revision. This must stay true — it is the load-bearing security property of §6/§7 |

## 13. Definition of done

- [ ] No generated code anywhere in the pipeline runs with `GEMINI_API_KEY` (or any secret) in its environment, proven by a test.
- [ ] Every dataset-backed quantitative claim produces `runs/{run}/notebooks/validate_{claim_id}.ipynb` that opens in Jupyter, carries its provenance block, and contains the recorded outputs that back its verdict.
- [ ] Each notebook states, in its own header, whether it can be re-run — and when it cannot, why.
- [ ] Network, filesystem, timeout, memory and output-size limits each have a passing contract test on the default tier.
- [ ] The sandbox tier that produced a verdict is visible in the UI.
- [ ] A reviewer can open a claim, read the notebook, edit a cell, re-run it in their browser, and save the result as a revision — without the server executing anything.
- [ ] The eight legacy run folders still render, badged as legacy, with no errors.
