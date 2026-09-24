# ASV — Value Proposition, Honest Assessment, and Market Position

**Status:** strategy memo. Opinionated by design.
**Date:** 2026-09-11
**Scope:** who actually gains value from ASV, what in it is real, what in it is theatre, what
exists in the market already, and what would have to change for this to be a thing worth
shipping rather than a thing worth demoing.

Every number about ASV's own behaviour in this document is measured from artifacts already in
`runs/`, not estimated. Reproduction recipes are in [Appendix A](#appendix-a--how-asvs-numbers-were-computed).
Companion document: [`SOURCE_ACQUISITION.md`](SOURCE_ACQUISITION.md) covers the engineering
detail of the acquisition layer; this document covers whether any of it matters to a user.

---

## 0. The one-paragraph verdict

ASV has built the unglamorous 80% of a citation-substantiation auditor — per-citation batching,
resolution manifests, honest download failure, reproducible run folders, cost-tiered LLM routing —
and attached it to a verdict layer that, on its own test corpus, **reported 224 of 306 claims as
"passed" while only 7 of those verdicts were backed by a retrieved passage from an actual source.**
The remaining 217 passes were an LLM being asked whether a sentence sounded plausible, with
`sources_used: []`. The infrastructure is the asset. The verdict layer is a liability — not because
it is unfinished, but because it manufactures the exact thing the project exists to oppose: a
confident-looking number with no evidence behind it. The path forward is not a better model. It is
source access, a verdict ontology that can say *"contradicted"* and *"I could not check,"* and a
published false-accusation rate. Do those three things and ASV owns a category. Skip them and it is
a weekend RAG script with a nicer folder structure.

---

## 1. What ASV actually is, mechanically

Stripped of the README's framing, the pipeline does five things:

| Stage | Mechanism | Code |
|---|---|---|
| 1. Claim extraction | PDF → text → 800-token chunks → Gemini Flash-Lite extracts sentence-level "claims" + spots citation markers + guesses `is_original` | `extraction/claim_extractor.py`, `llm_client.py` |
| 2. Routing | 2×2 split on (quantitative \| qualitative) × (cited \| uncited); cited claims batched by `citation_id` | `orchestrator/claim_orchestrator.py` |
| 3. Source acquisition | bibliography string → LLM parse → Unpaywall / Semantic Scholar / CrossRef / Scholar cascade → HTTP fetch → PDF or HTML text extraction, with a 200-char usable-text gate | `sourcefinder/academic_paper_finder.py`, `text_downloader.py` |
| 4. Judgment | **cited:** TF-IDF top-3 chunks (cosine ≥ 0.15) → Gemini Flash returns `{passed, confidence, explanation, supporting_quotes}`.  **uncited:** Gemini Flash-Lite answers "is this plausible?" from priors.  **dataset-backed quant:** Gemini Pro writes a pandas script, which is executed with a 30s timeout | `validator/llm_verifier.py`, `python_script_validator.py` |
| 5. Output | 4 JSON files + run summary + manifests, surfaced through a FastAPI + React app with a claims explorer, PDF highlighting, SSE log stream, and run-to-run compare | `apps/api/`, `apps/web/` |

Roughly 3,800 lines of first-party Python/TypeScript, 136 tests (all in extraction and the API
read model; the orchestrator, validator, and sourcefinder have no dedicated test modules).

**The important structural fact:** the four routing buckets have wildly different epistemic
status, and the output format treats them as equivalent. A claim can be "passed" because a
retrieved passage from the cited paper supports it, or because a small language model thought it
sounded right. Both land in a `ValidationResult` with a `confidence` float, and both render
identically in the UI's verdict badge.

---

## 2. Measured reality: what one full run produced

Input: `pdfs/hsv_cancer.pdf`, a virology review paper with 253 references.
Run: `runs/hsv_cancer__20260706_192057`, 766 seconds wall clock.

### 2.1 Where the 306 claims went

| Bucket | Claims | "Passed" | Avg confidence | Evidence actually used |
|---|---:|---:|---:|---|
| Qualitative, uncited | 233 | 207 | 0.886 | **none** — LLM priors |
| Quantitative, uncited | 14 | 10 | 0.643 | **none** — LLM priors (+1 `source_not_found`) |
| Qualitative, cited | 45 | 6 | 0.191 | retrieved passages, when download worked |
| Quantitative, cited | 14 | 1 | 0.071 | retrieved passages, when download worked |
| **Total** | **306** | **224** | — | — |

### 2.2 The funnel that matters

```
306 claims extracted
 ├─ 247 (81%) routed to the unsourced plausibility path ──► 217 "passed" with sources_used: []
 └─  59 (19%) routed to the source-grounded path
      ├─ 37 (63%) lost to download failure           ──► verdict: failed, conf 0.0, no evidence
      └─ 22 (37%) had a source in hand
           ├─ 12  "No relevant chunks found"         ──► retrieval failure, reported as a failed claim
           ├─  3  substantive negative judgment      ──► a real, useful finding
           └─  7  substantive positive judgment      ──► a real, useful finding
```

**10 of 306 claims (3.3%) received a judgment that an evidence passage participated in.**
**97% of all "passed" verdicts (217 of 224) had no source behind them at all.**

### 2.3 Source acquisition, across four runs on identical input

| Run | Batches | Downloaded | Rate |
|---|---:|---:|---:|
| `20260703_162705` | 37 | 18 | 49% |
| `20260704_103453` | 51 | 24 | 47% |
| `20260704_110320` | 51 | 21 | 41% |
| `20260706_192057` | 51 | 16 | **31%** |

80% of failures are HTTP 403 from publisher hosts. The monotone decline on identical input is
rate-limiting and bot-heuristic accumulation with no cache, no backoff, and no per-host politeness.
Ten of sixteen "successes" in the last run were `nature.com` HTML landing pages — abstract and
reference list only. RAG then searched a document that could not contain the evidence. Full
breakdown in [`SOURCE_ACQUISITION.md §4–5`](SOURCE_ACQUISITION.md).

### 2.4 Three failures that are worse than not running

**(a) The plausibility path inverts the tool's own thesis.** ASV exists because "technically true
but unsupported" assertions are dangerous. Its dominant code path produces exactly that: a
`confidence: 0.9` attached to *"HSV-1 is indeed a neurotropic DNA virus… this is a well-established
area of research."* That is not validation. It is an LLM agreeing with a sentence, formatted as a
measurement. Downstream, a user filtering for `passed: false` sees 26 of 233 — and reasonably
concludes 89% of the paper's uncited claims checked out. Nothing was checked.

**(b) It penalises novelty by construction.** 25 claims were tagged `is_original` and routed to the
plausibility path; 22 "passed." A genuinely new finding is, by definition, not in the model's
priors, so it scores *low*; a textbook platitude scores 1.0. A validator whose confidence tracks
conformity-to-consensus is anti-correlated with the thing science values. (Separately, on this
review paper the `is_original` classifier misfired badly — "The most frequently used suicide gene
is the native HSV-1 thymidine kinase gene" is a summary of others' work, not an original
contribution.)

**(c) The dataset/script path hallucinates its own evidence.** From
`runs/hsv_cancer__20260703_162705/generated_scripts/validate_claim_2_5.py`, generated to check
*"the transition from attached to penetrated virus… occurs within minutes"*:

```python
required_cols = ['attachment_time_minutes', 'penetration_time_minutes']
```

Those columns were invented. The "dataset" was a CrossRef bibliographic record fetched from a DOI.
The claim was not quantitative in any checkable sense. Three independent failures compounding —
and the pipeline executes the resulting LLM-authored code locally with no sandbox.

### 2.5 Upstream causes worth naming

- **Citation attribution under-recalls badly.** 182 of 306 claims were marked uncited in a review
  paper where nearly every sentence carries a reference. Causes: markers are spotted per-chunk by
  the LLM, chunk boundaries split them, paragraph-level citations are not inherited by their
  sentences, and the extraction prompt shows the model only **the first 10 references, truncated to
  100 characters each** (`llm_client.py`: `list(available_citations.items())[:10]`). Every
  misattributed claim falls into the weakest validation path — the extraction bug *feeds* the
  plausibility path.
- **29% of claims (89/306) could not be located in the source text** (`location_in_text.start is
  None`), because the LLM paraphrased. Those claims cannot be highlighted, cited back, or audited.
- **No calibration and no ground truth.** There is no labelled set, so no precision, no recall, no
  false-accusation rate. Every quality statement about ASV — including the optimistic ones — is
  currently anecdote.
- **Cost accounting is wrong.** `llm_client.get_cost_summary()` hardcodes $0.10/$0.40 per M tokens
  for every tier including Gemini Pro, and nothing logs cost for the orchestration stage at all.

---

## 3. Does anyone actually have this problem?

The failure mode of tools in this space is building for a user who does not experience the pain
the tool relieves. So: segment by segment, does the problem exist, is it felt, and is there money.

### 3.1 The problem is real and well-quantified

This part is not in doubt. Across meta-analyses of the medical literature, **14.5%–25.4% of
quotations misrepresent their source**, and roughly **65% of content errors are *major*** — the
cited source fails to substantiate, is unrelated to, or outright contradicts the assertion.
Improper secondary citation (citing A for a number that A itself attributed to B) runs ~10%.
Meta-regression shows **no improvement over time**. Separately, the AI-writing era has added a new
failure class: roughly **1 in 277 papers in early 2026 cited at least one reference not findable in
any major bibliographic database — a 12× increase in two years.**

So: a 1-in-6 error rate on a practice that the entire edifice of scientific credibility rests on,
getting worse, with a new and more embarrassing variant. The problem is real.

### 3.2 But "real problem" ≠ "felt problem"

| Segment | Do they have the problem? | Do they *feel* it? | Budget | Verdict |
|---|---|---|---|---|
| **Individual researchers (authors)** | Yes — they are the ones making the errors | **Barely.** Miscitation has essentially zero consequence. Nobody checks; reviewers rarely catch it; it almost never triggers correction | Personal, ~$0–20/mo | ⚠️ Real problem, near-zero felt pain. **Do not build the business here** |
| **Researchers using AI writing tools** | Yes, acutely | **Yes.** A hallucinated reference is a career-visible humiliation, and the base rate is climbing | Personal, low | ✅ Felt pain — but the acute part (*does it exist?*) is a 200 ms API lookup, already commoditized |
| **Peer reviewers** | Yes — it is literally their assigned job | Yes, but as *time cost*, not risk | **Zero.** Unpaid labour | ❌ Cannot monetize. ✅ Excellent free-distribution channel |
| **Journal editors / publishers** | Yes, at volume (Elsevier alone: ~1.2M manuscripts/yr) | Yes — retraction volume (14k in 2023; 63k+ in the Retraction Watch DB), paper mills, reputational exposure | Real, enterprise | ⚠️ Right budget, wrong first sale: 12–18 month cycles, incumbent integrations, and they want **triage scores**, not verdicts |
| **Evidence synthesis / systematic reviews / HTA / guidelines** | Yes — and they already do this work **manually and by mandate** | **Yes.** Dual independent extraction and source verification are required steps, and they are the bottleneck | Real, per-project and per-seat (DistillerSR is enterprise-priced) | ✅ **Strongest under-served fit** |
| **Pharma medical affairs / MLR review** | Yes — every promotional and scientific claim must be tied to a substantiating reference, and reviewed | **Acutely.** FDA/OPDP enforcement, warning letters, personal and corporate liability | Large, compliance line-item | ✅ **Highest willingness to pay per seat in the space** |
| **Regulatory / patent / expert witness** | Yes | Yes — a miscited source is a defensible-file problem | Large | ✅ Adjacent, same shape |
| **Journalists / fact-checkers / policy analysts** | Yes — especially press-release-vs-paper exaggeration | Yes, but episodically | Very low | ⚠️ Good free wedge, bad business |
| **Funders / research offices / integrity officers** | Yes | Emerging | Institutional | ⚠️ Watch; slow |

### 3.3 The pattern

**Nobody pays for "validate my paper." People pay when a wrong citation costs them money, a
license, or a job.** In science that is almost never the author. It is the evidence-synthesis
analyst whose review will be audited, the regulatory writer whose dossier will be challenged, and
the pharma medical reviewer whose signature is on a promotional piece the FDA can act against.

Clearbrief proves the price elasticity precisely: the *same technical capability* — "does the
cited source actually support this sentence?" — sells for **$300/user/month in litigation**, where
a judge can sanction you for getting it wrong, and for **$6–20/month in academia**, where nothing
happens. That is a 15–50× spread driven entirely by consequence, not by capability.

**Price to liability, not to academia.**

### 3.4 The uncomfortable corollary for ASV's stated premise

ASV's README opens with statistical misrepresentation: means of skewed data, base-rate fallacies,
"the average person has fewer than two arms." That is a genuinely important and genuinely
under-served problem. **It is also not what the pipeline does.** What the pipeline does is textual
entailment between a sentence and a retrieved passage. To catch "this mean is misleading because
the distribution is skewed" you need the underlying data, which is unavailable for the overwhelming
majority of citations — and where it *is* available, the current dataset path searches data.gov and
Kaggle with a truncated raw claim sentence, which for a virology corpus has literally zero overlap.

There is a way to recover the original thesis without needing the raw data. It is in §6. It is, in
my read, the single most valuable idea in this document.

---

## 4. Where ASV creates real value today

Being frank cuts both ways. These are genuine, and several are things competitors get wrong.

**1. Honest failure is an architectural commitment, not an afterthought.** The 200-char usable-text
gate, `download_successful: false`, the explicit refusal to fall back to plausibility when a source
is missing — this is the single best decision in the repository. A tool that says "I could not
check this" is worth more than one that guesses, and the naive version of this product (see §5, L8)
*always* guesses, because guessing produces a prettier demo. ASV already chose correctly here. The
plausibility path is the one place the commitment leaks, and it is removable.

**2. Per-citation batching matches the real cost structure.** Downloading once per `citation_id`
and verifying N claims against it is the correct optimization, and it falls out of a correct model
of the domain rather than from profiling. A 250-reference review paper with 3 claims per reference
is 3× cheaper and 3× politer to publishers under this design.

**3. Resolution manifests are compliance-grade provenance.** `SourceManifestEntry` records every
candidate URL, its source label, its outcome, and its error — and survives the post-batch file
deletion. This is exactly what an auditor, an editor, or a regulator needs and almost never gets
from an AI tool. It is also the raw material for the acquisition improvements in §7.

**4. Run isolation makes the tool falsifiable.** Timestamped run folders holding every artifact,
plus a compare endpoint, means you can A/B a change and see the effect. Most tools in this
category cannot tell you whether they got better or worse last Tuesday.

**5. The routing insight is correct.** Recognizing that "cited quantitative" splits into
dataset-backed and paper-backed — and that the second is really the qualitative path with numbers
in it — is a genuinely right modelling call that a naive implementation misses.

**6. Cost-tiered task routing.** `LLM_TASK_CONFIG` with per-task model tiers, budgets, and
escalation hooks is the right shape for a product whose margin depends on not calling a frontier
model 306 times per paper.

**7. There is already a real product surface.** A React app with a claims explorer, faceted
filters, PDF highlight overlay, live SSE progress, per-citation retry, and run comparison. Most
projects at this stage have a CLI and a JSON dump.

**8. The team writes down its own failures.** `SOURCE_ACQUISITION.md` is a better piece of
self-criticism than most companies produce under duress. That is a real organizational asset and
should be preserved as the project grows.

---

## 5. The competitive landscape

The right way to see this market is as layers of increasing difficulty. ASV is aiming at L3 while
having skipped L1, and while L4 quietly outperforms it on quantitative claims.

### L1 — Does the reference exist? *(commoditized)*

| Product | What it does | Overlap |
|---|---|---|
| **Signals** (Research Signals; ACS/Enago-backed) | Flags three classes of invalid reference at submission, surfaced inside ScholarOne / Editorial Manager | Direct on existence, none on substantiation |
| **Paperpal Preflight** (Cactus) | 30+ pre-submission checks in <2 min incl. reference verification, AI-content, similarity | Direct on existence |
| **HalluCiteChecker** (open source) | Laptop-runnable hallucinated-citation detector, matched against bibliographic DBs | Direct on existence |
| **Crossref / OpenAlex / PubMed lookup** | A free API call | This is the whole of L1 |

**Assessment:** solved, free, table stakes. **ASV does not currently do it** — it goes straight to
full-text acquisition. Ship existence + retraction checking, never charge for it, and use it as the
free tier. Retraction checking is a distinct and separately valuable signal: a 2026 JMIR study
found freely available AI tools cannot reliably flag retracted literature, and authors keep citing
retracted work regardless of notices.

### L2 — What does the literature say about this paper? *(different job, huge distribution)*

| Product | What it does | Price |
|---|---|---|
| **scite.ai** | 1.6B+ citation statements classified supporting / contrasting / mentioning, with context | $20/mo individual; $30/user/mo team |

**Assessment:** not a competitor to ASV's core — scite tells you how *others* cited a paper, not
whether *your* sentence is supported by the paper *you* cited. But scite has the corpus, the
distribution, and the obvious adjacency to move into L3. It is the most likely party to make ASV's
core a feature. Treat as the strategic threat.

### L3 — Does the cited source substantiate *this* claim? *(ASV's core — and no longer empty)*

| Product | What it does | Price | Where ASV could beat it |
|---|---|---|---|
| **CiteDash AI** | Four verdicts — supported / partial / unsupported / unverified — judged against **full text only**, explicitly refusing abstracts as evidence. Verifies inside a thesis-writing workflow | $6–20/mo | CiteDash verifies *its own* library and its own generated text. It does not audit an arbitrary finished PDF with 250 references you never imported. **That gap is ASV's opening** |
| **Manusights Verify** | Free single-sentence "does this paper support my claim," judged from the **abstract** | Free | Abstract-only is precisely the failure mode `SOURCE_ACQUISITION.md §F3` identifies. Full text + honest abstention beats it |
| **Clearbrief** | Legal cite-check as a Word add-in; patented semantic score comparing a sentence to its cited source; "Cite Check Report" audit trail for partners | **$300/user/mo** + $1k–7.5k implementation | Not competing in science. **It is the proof that this capability is worth 15–50× academic pricing when liability attaches** |
| **Westlaw Quick Check / Lexis Brief Analysis** | Same job, incumbent-distribution version | Enterprise | Same lesson |
| **DeepSciVerify, SciLens, RIGOURATE** (research, not products) | Claim–citation alignment with evidence escalation (86.7 micro-F1 on SCitance); exaggeration quantification | — | This is where the technique is going. ASV's TF-IDF + top-3 is two generations behind. **Adopt, don't reinvent** |

**Assessment:** this layer was empty 18 months ago and is not empty now. CiteDash in particular has
already shipped the graded verdict ontology ASV lacks and made the correct
"full-text-or-abstain" call. ASV's *architecture* is better suited to the audit use case; its
*judgment layer* is behind.

### L4 — Is the paper internally consistent? *(free, deterministic, and a lesson)*

| Tool | What it does |
|---|---|
| **statcheck** | Recomputes p-values from reported test statistics and df. Found ~50% of psychology articles contain an inconsistent p-value; in 1 in 8, recomputation flips the conclusion |
| **GRIM / SPRITE / scrutiny** | Checks whether a reported mean is arithmetically possible given N and integer data; reconstructs plausible distributions |
| **SciScore** | Methods-rigor and reporting-standards scoring |

**Assessment:** not competitors — **complements ASV should ship**. And they carry the most important
lesson in the space: *statcheck is trusted precisely because it abstains everywhere it cannot be
certain.* It checks one narrow thing, deterministically, with near-zero false positives, and as a
result it is used by journals and cited in meta-research. It required no LLM. ASV's quantitative
ambitions would be better served by ten statcheck-shaped deterministic detectors than by one
LLM-written pandas script.

### L5 — Integrity screening at publisher scale *(enterprise, incumbent)*

**STM Integrity Hub** (cross-publisher; incorporates Clear Skies' Papermill Alarm), **Clear Skies
Oversight**, **Signals**, **Proofig / ImageTwin** (image forensics), **Silverchair ScholarOne
Relay** (the integration substrate). The operating model is the "Swiss cheese" stack: many
imperfect screens layered. Publishers buy *signals feeding a triage queue*, not verdicts.

**Assessment:** if ASV ever sells to publishers, it sells as **one more slice of cheese** delivered
through Relay/ScholarOne, scored and ranked — not as a standalone verdict engine. Plan for that
integration surface early; do not plan for that sale early.

### L6 — AI research assistants that generate cited claims *(the cause of the problem — and a customer)*

**Elicit, Consensus, SciSpace, Scopus AI, Undermind, Perplexity.** They produce cited output at
volume. They are simultaneously the cause of the demand shock and the most natural **buyers** of a
verification layer — a "verified by" API is a real product. Note their bar: Stanford work in 2026
reports multi-layer validation achieving <1% hallucination vs 17–33% for naive retrieval.

### L7 — Evidence synthesis platforms *(where the budget and the mandate already are)*

**Covidence** (Cochrane-recommended), **DistillerSR** (enterprise/regulated, audit trails),
**Rayyan**, **Nested Knowledge**, **Elicit's SR workflow** (screening up to 40k papers on
enterprise). These already enforce structured extraction and dual verification.

**Assessment:** ASV's per-citation batching, manifests, and audit trail fit *this* workflow better
than they fit author self-checking. This is the partner-or-compete decision worth making
deliberately rather than by default.

### L8 — The real competitor: a chat model and a PDF

This is the baseline every product in this space must beat, and the one most pitch decks omit.

A researcher today can drop a paper into Claude or GPT-5 with browsing and ask "check whether
reference 34 supports the sentence citing it." For **one** citation that is faster, more accurate,
and more flexible than ASV — it handles figures and tables, follows a secondary citation, argues
with you, and costs nothing marginal.

Where that baseline breaks is the only defensible ground ASV has:

| Dimension | Chat model + PDF | Where ASV must win |
|---|---|---|
| 1 citation | Wins outright | — |
| 250 citations | Falls apart: context limits, no batching, no state | **Batching + run state** |
| Source acquisition | Whatever the browser tool reaches; silently settles for abstracts | **A real acquisition layer: OA aggregators, TDM tokens, institutional auth, cache** |
| Abstention | Answers from priors when it can't fetch — the exact failure ASV's 200-char gate prevents | **Enforced abstention** |
| Audit trail | None; unreproducible | **Manifests, run folders, per-claim provenance** |
| Calibration | Unknown and unmeasurable | **A published false-accusation rate** |
| Determinism | None | **Cached, seeded, reproducible runs** |

**The vibecode test.** Anyone can build "chunk a PDF, embed it, ask an LLM if the claim is
supported" in an afternoon, and the demo will look better than ASV's current output. What cannot be
built in an afternoon: a high-yield, legally clean full-text acquisition layer; a calibrated
abstention policy with a measured error rate; and a provenance trail a third party can act on.
**Those three are the entire moat. Everything else in this repository is scaffolding around them —
and right now, all three are the least-developed parts of the system.**

---

## 6. The differentiation thesis: the miscitation taxonomy

This is the part I would build the company on.

Every L3 competitor asks one binary question: *does the source support the claim?* That is the easy
half. The literature on quotation error says the interesting failures are **specific, recurring,
and textually detectable** — and nobody ships detectors for them. Better still, they are the honest,
achievable form of ASV's original "technically true but misleading" thesis, and they need only the
source text ASV already downloads.

| # | Failure mode | What it looks like | Detectable from text alone? |
|---|---|---|---|
| M1 | **Generalization drift** | Source studied 40 mice; claim asserts it of humans. Source studied one Danish cohort; claim says "globally" | **Yes** — compare the claim's population/scope to the source's stated sample |
| M2 | **Hedge stripping** | Source: "may be associated with." Citing paper: "causes" | **Yes** — modality comparison. Directly the RIGOURATE exaggeration line |
| M3 | **Causal upgrade** | A correlational finding cited as a causal mechanism | **Yes** — design of the source vs. verb of the claim |
| M4 | **Numeric drift** | Claim says 43%; source says 34%, or 43% of a different denominator | **Yes** — extract (value, unit, denominator, population, window) and compare component-wise |
| M5 | **Temporal / scope drift** | A 2005 single-centre figure cited as a current national rate | **Yes** — date and setting of source vs. framing of claim |
| M6 | **Chain citation** | The cited source does not contain the finding; it cites *another* paper for it. ~10% of quotation errors | **Yes** — follow one hop and report provenance depth |
| M7 | **Substantiation failure** | The source is unrelated, or contradicts. The ~65%-of-content-errors "major" bucket | **Yes** — this is the L3 baseline everyone already does |

Shipping M1–M6 alongside M7 gives ASV something no competitor has: **a typed, explainable finding
rather than a thumbs-down.** *"Reference 34 reports this in a murine model; your sentence states it
of patients"* is a finding a reviewer can act on, an editor can send to an author, and an author
cannot dismiss. *"Not supported, confidence 0.31"* is noise.

It also resolves the founding tension in §3.4. ASV was conceived to catch statistics that mislead
while being true. M1–M5 are exactly that, computed on text rather than on raw data — which is the
only form of the problem that is solvable at scale.

---

## 7. What to change: a sequenced plan

Ordered by (credibility × leverage) ÷ effort. Tier 0 is non-negotiable before anyone outside the
project should see a verdict from this system.

### Tier 0 — Stop producing unearned confidence *(weeks, mostly deletion)*

| # | Change | Why |
|---|---|---|
| 0.1 | **Delete the plausibility verdict.** Uncited claims get `status: not_checkable`, `reason: no_source_available`. No `passed`, no `confidence`. Keep the LLM opinion only as an explicitly non-evidentiary note, if at all | It is 81% of output and 97% of "passes." Biggest correctness and credibility problem in the system |
| 0.2 | **Replace `passed: bool` with a verdict ontology:** `substantiated` / `partially_substantiated` / `not_substantiated` / `contradicted` / `not_checkable(reason_code)` | "Source is paywalled" and "the source says the opposite" are currently the same output. They imply opposite user actions. CiteDash already ships four verdicts |
| 0.3 | **Content-quality gate:** classify every fetch as `full_text` / `abstract_only` / `paywall_interstitial` / `rejected`; refuse to judge on `abstract_only`; raise the HTML floor from 200 chars to a structure test | 10 of 16 "wins" in the last run were abstract-only Nature pages. A confident verdict off an abstract is worse than a failure |
| 0.4 | **Build a gold set: 200–300 hand-labelled claim–source pairs** across ≥3 fields, including hard negatives. Publish precision, recall, and **false-accusation rate** with a calibration curve. Seed from SciFact / SCitance / CiteME, but hand-audit — a 2026 audit found 5.3% gold-label errors in SciFact's dev set | Without this, no claim about ASV's quality is defensible and no serious buyer can adopt it |
| 0.5 | **Never emit a verdict without a quoted span and a resolvable source URL** | Makes every finding checkable by a human in ten seconds |

### Tier 1 — Source acquisition, the actual moat *(highest-yield engineering work)*

| # | Change | Expected effect |
|---|---|---|
| 1.1 | **Union-then-rank** instead of first-hit-wins resolution | 32/51 batches currently have exactly one candidate; one 403 kills the batch. Largest single recoverable yield |
| 1.2 | **Add Europe PMC, PMC OA, OpenAlex, bioRxiv/medRxiv, DOAJ, DataCite** | The three services that would most directly fix a biomedical corpus are not queried at all |
| 1.3 | **Publisher TDM programmes** — Wiley returns `400 No TDM Client Token`, i.e. it is naming the header it wants; Elsevier and Springer Nature have equivalents | Converts a class of 400/403s into legitimate, ToS-compliant full text |
| 1.4 | **Content-addressed HTTP cache + `Retry` with backoff + per-host token bucket** | Kills the 49%→31% drift, makes runs reproducible enough to A/B every other change, and stops hammering `asm.org` |
| 1.5 | **Persist Playwright `storage_state`; trigger the login prompt from *resolved hosts*, not bibliography text** | The login checkpoint never fires today, and then the run 403s 41 times on exactly those publishers |
| 1.6 | **Classify citation kind**; give books, chapters, and personal communications a terminal `unresolvable_by_design` status | Makes the headline metric honest and stops burning API calls on textbooks |
| 1.7 | **Fix citation attribution**: full reference list in context (not first-10-truncated-to-100-chars), marker-preserving chunking, paragraph-level citation inheritance | Directly shrinks the unsourced bucket, which is the root cause of the Tier-0 problem |

### Tier 2 — Judgment quality

| # | Change |
|---|---|
| 2.1 | Replace TF-IDF with hybrid retrieval (embeddings + BM25) and section-aware chunking; prefer Results/Methods for quantitative claims. TF-IDF misses paraphrase — which is exactly how citations are miscited |
| 2.2 | **Structured numeric verification**: parse the claim into (value, unit, direction, population, denominator, time window) and check each component against the source separately. Foundation for M4 |
| 2.3 | **Second-opinion adjudication on low-margin cases only** — a stronger model reruns disagreements and near-threshold calls. Cost-aware, and the cheapest route to a lower false-accusation rate |
| 2.4 | Distinguish *retrieval failure* from *claim failure*. "No relevant chunks found" hit 12 of 22 successfully-downloaded claims and was reported as a failed claim. It is not |
| 2.5 | Ship the **M1–M6 detectors** from §6 |

### Tier 3 — Product shape

| # | Change |
|---|---|
| 3.1 | **Triage.** Rank by `load-bearing × checkable × risk`. Load-bearing ≈ appears in abstract/conclusions, is numeric, or is a safety/efficacy statement. A 306-row table is unusable; a ranked top-20 is a work product |
| 3.2 | **Outputs that fit a workflow**: reviewer memo, annotated PDF/Word markup, per-citation evidence card, machine-readable JSON |
| 3.3 | **Integrations by segment**: Word/Overleaf (author) · ScholarOne / Editorial Manager / Silverchair Relay (editor) · DistillerSR / Covidence (synthesis) · Veeva PromoMats (pharma MLR) |
| 3.4 | Determinism and per-run cost reporting (and fix the hardcoded flat token pricing) |
| 3.5 | Tests for orchestrator / validator / sourcefinder — the three modules that produce every user-visible verdict currently have none |

### Tier 4 — Cut these

| Cut | Why |
|---|---|
| **LLM-written pandas scripts, executed unsandboxed** | Hallucinates columns, runs against non-datasets, and is an RCE surface on untrusted PDFs. Replace with a whitelisted DSL of deterministic checks (recompute mean, %, ratio, CI, GRIM) |
| **`DatasetFinder` over data.gov + Kaggle** | Zero corpus overlap for biomedical work; `_rank_candidates` is `max()` over hardcoded constants. Either retarget at DataCite/Dryad/Zenodo/OpenAIRE for a domain where it works (economics, public health, government statistics), or cut it |
| **Google Scholar scraping** | Returns nothing 100% of the time and is explicitly hostile to automation. Legal and reliability liability for zero yield |
| **Google Fact Check API (truth table)** | Near-zero coverage of academic claims; currently emits "No API key configured" into 233 user-facing explanation strings |
| **`INSTITUTIONAL_COOKIES` as a primary path** | Hand-assembled JSON from DevTools, redone every few weeks, keyed by exact netloc so `nature.com` silently misses `www.nature.com`. Demote to an escape hatch behind the Playwright flow |

---

## 8. Metrics that would prove this works

Replace "224 of 306 passed" — which measures nothing — with:

| Metric | Definition | Target to be credible |
|---|---|---|
| **Checkable rate** | claims with a citation whose full text was obtained | >70% (today: 31% of batches) |
| **Full-text purity** | obtained sources that are full text, not abstracts | >90% (today: ~35%) |
| **False-accusation rate** | claims marked `not_substantiated`/`contradicted` that a human expert judges correctly cited | **<5%, and published** |
| **Recall on seeded errors** | detection rate on deliberately corrupted claim–source pairs | >70% per category (M1–M7) |
| **Abstention correctness** | of `not_checkable` claims, the fraction genuinely unobtainable | >90% |
| **Calibration (ECE)** | reported confidence vs. observed accuracy | ECE < 0.1 |
| **Cost & latency per 100 references** | measured, including model-tier mix | <$2, <5 min |
| **Determinism** | verdict agreement across two runs on identical input | >95% |

The order matters: **false-accusation rate is the one that decides whether this is a product or a
liability.** A tool that tells a researcher their citation is wrong when it isn't will be
uninstalled after the second occurrence and never recommended again.

---

## 9. Recommendation

### Beachhead: evidence synthesis and regulated claim substantiation

Go where claim–source verification is **already a mandated, budgeted, audited step**:

1. **Systematic review / HTA / guideline teams.** They perform this work manually today, under
   protocol, with dual extraction and audit trails. ASV's batching, manifests, and abstention map
   onto their workflow directly. They value *"we could not verify"* — for them it is a
   protocol-compliant outcome, not a product failure. Sell per project or per seat; partner with or
   plug into DistillerSR/Covidence rather than replacing them.
2. **Pharma medical affairs / MLR review.** Every promotional and scientific claim must be linked to
   a substantiating reference and reviewed before release, with regulatory liability attached. This
   is literally ASV's data model, performed by expensive humans, inside Veeva. Highest willingness
   to pay per seat in the space by a wide margin.

Both segments share the property that makes ASV viable: **the cost of a missed error exceeds the
cost of an abstention**, which is the regime ASV's architecture is already built for.

### Free wedge: the pre-submission citation audit

Narrow it hard — *"we checked the 62 of your 210 references we could obtain in full text; here are 4
findings, and here are the 148 we could not check, with reasons."* Give it away. It builds the
labelled corpus, it builds the brand with reviewers and editors, and it is honest in a way this
market will notice. It is not a business on its own; CiteDash is already at $6/month and the
marginal buyer is a graduate student.

### Do not chase first

- **Individual researchers as the paying customer.** Real problem, no felt pain, no budget,
  crowded, and already priced at $6–20/month by incumbents.
- **Publishers as the first enterprise sale.** Correct budget, wrong sequence: long cycles,
  entrenched integrations, and they want triage signals inside an existing queue. Revisit once §8's
  metrics exist — they are the entry ticket to that conversation.
- **Anything requiring raw research data.** The data is not there, and the dataset path is currently
  producing hallucinated evidence. Recover the "misleading statistics" thesis through the text-only
  M1–M5 detectors instead.

### Three honest paths forward

| Path | What it means | Requires | Honest odds |
|---|---|---|---|
| **A. Research contribution** | Publish the miscitation taxonomy (§6) with a labelled benchmark and detector baselines. The acquisition failure analysis is itself publishable meta-research | Tier 0.4 + M1–M6 + a corpus | **High.** The gold set and taxonomy are novel and genuinely useful, and this is the path most compatible with a university setting |
| **B. Free public good** | An abstention-first citation auditor, open source, used by reviewers and integrity sleuths | Tier 0 + Tier 1 | **Moderate.** Needs sustained funding for the acquisition layer, which is the expensive part |
| **C. Commercial** | Per-seat tool for evidence synthesis and regulated claim substantiation | Tiers 0–3, a published false-accusation rate, and a design partner in one of the two beachhead segments | **Moderate, conditional.** Gated entirely on §8's metrics. Do not raise or sell on the current verdict layer |

They are compatible in that order. A produces the evidence base that makes B trustworthy and C
sellable.

---

## 10. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| **False accusation.** A verdict of "this citation does not support this claim" is an allegation. At today's uncalibrated accuracy over 124 cited claims, even a 10% FP rate is ~12 wrong accusations per paper | **Critical** | Abstention-first; mandatory quoted span; human-in-the-loop framing ("review this") rather than automated judgment; published FP rate; never name authors in aggregate output |
| **Scraping publishers against ToS.** 403s are bot-blocks, and the response so far has been to look more like a browser | **High** (legal + relational) | Move to legitimate channels: OA aggregators, TDM tokens, institutional auth. Rate-limit. Retire the Scholar scrape |
| **Defamation-adjacent exposure** if outputs are published about named authors | High | Private-by-default reports; findings go to the author or editor, not a public leaderboard. The Black Spatula Project contacts authors privately rather than publishing — a good precedent to copy |
| **LLM nondeterminism** undermining an audit trail | Medium | Cache prompts and responses; seed; record model and prompt version in every result |
| **Incumbent absorption.** scite, Paperpal, or Elicit ships this as a feature | High | Speed on the taxonomy (§6) and the acquisition layer; partner rather than compete on distribution |
| **The "good enough chatbot" floor rising** | High | Only the moat in §5/L8 survives this. Invest there and nowhere else |
| **Unsandboxed execution of LLM-generated code** on untrusted PDFs | Medium (rising with adoption) | Tier 4 cut |

---

## 11. Summary

- The problem ASV targets is real, large, measured (14.5–25.4% quotation error, ~65% of those
  major), and getting worse under AI-assisted writing.
- ASV has built the right *infrastructure* for it and the wrong *verdict layer*. 97% of its passes
  are unsourced; 3.3% of claims received an evidence-backed judgment.
- The L3 category — claim-to-cited-source substantiation — was empty 18 months ago and is not empty
  now. CiteDash ships the graded verdicts ASV lacks; Clearbrief proves the price ceiling in a
  vertical where liability attaches.
- ASV's defensible ground is exactly three things: **source acquisition, calibrated abstention, and
  provenance.** All three are currently its weakest components, and all three are the parts a
  competitor cannot reproduce in an afternoon.
- The differentiating product is the **miscitation taxonomy** (§6) — typed, explainable findings
  instead of a thumbs-down — which also rescues the project's founding thesis about
  misleading-but-true statistics in the only form solvable at scale.
- Sell to whoever is liable. In science that is the evidence-synthesis analyst and the regulatory
  reviewer, not the author.

---

## Appendix A — How ASV's numbers were computed

All from `runs/hsv_cancer__20260706_192057/` unless noted. Run from the repo root.

```python
import json, io, collections
B = 'runs/hsv_cancer__20260706_192057/'
L = lambda p: json.load(io.open(B + p, encoding='utf-8'))   # note: utf-8, not cp1252

# §2.1 bucket totals
print(L('final_output/run_summary.json')['steps'])

# §2.2 funnel over the source-grounded path
tot = grounded = passed = nochunk = 0
for f in ('qualitative_cited_results.json', 'quantitative_cited_results.json'):
    for b in L('validation_results/' + f):
        for cr in b['claim_results']:
            tot += 1
            if b['download_successful']:
                grounded += 1
                passed  += cr['passed']
                nochunk += 'No relevant chunks' in (cr['explanation'] or '')
print(tot, grounded, passed, nochunk)     # -> 59 22 7 12

# §2.1 unsourced passes
u = L('validation_results/qualitative_uncited_results.json') \
  + L('validation_results/quantitative_uncited_results.json')
print(sum(r['passed'] for r in u), sum(not r['sources_used'] for r in u))   # -> 217, 247

# §2.5 claim routing and span-location failures
c = L('citations/hsv_cancer_claims.json')['claims']
print(collections.Counter(x['citation_found'] for x in c))                       # 182 False
print(sum((x.get('location_in_text') or {}).get('start') is None for x in c))    # 89

# §2.3 acquisition rates: runs/*/text_sources/_manifest.json
#      — see SOURCE_ACQUISITION.md Appendix A
```

Test/coverage figures: `python -m pytest --collect-only -q` (136 tests; all under
`src/asv/extraction/tests/` and `apps/api/tests/`).

---

## Appendix B — Sources

**Research integrity & the scale of the problem**
- [Accuracy of cited "facts" in medical research articles (PLOS One)](https://journals.plos.org/plosone/article?id=10.1371%2Fjournal.pone.0184727)
- [Systematic review and meta-analysis of quotation inaccuracy in medicine (PMC)](https://pmc.ncbi.nlm.nih.gov/articles/PMC12285159/)
- [Quotation accuracy in medical journal articles — systematic review and meta-analysis (PMC)](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC4627914/)
- [How do authors perceive the way their work is cited? (JASIST, 2025)](https://asistdl.onlinelibrary.wiley.com/doi/10.1002/asi.70000)
- [Research paper retraction statistics 2026](https://tesify.app/research-paper-retraction-statistics-2026/)
- [Retraction Watch — citation rates of retracted/corrected articles (2026)](https://retractionwatch.com/2026/04/27/citation-rates-retracted-corrected-articles-asemi-clinical-trials/)
- [Checking citations for retractions before journal submission (2026)](https://www.journalmetrics.org/blog/checking-retracted-citations-medical-manuscripts-2026)

**Citation verification tools & benchmarks**
- [CiteDash — how verified citations work: the four verdicts](https://citedash.ai/blog/how-verified-citations-work) · [pricing](https://citedash.ai/pricing)
- [Manusights Citation Claim Checker](https://manusights.com/tools/citation-claim-checker)
- [scite.ai](https://scite.ai/) · [Scite review & pricing 2026](https://elephas.app/blog/scite-ai-review)
- [Clearbrief launches Cite Check Report (LawSites)](https://www.lawnext.com/2025/12/clearbrief-launches-cite-check-report-to-give-law-firm-partners-an-audit-trail-against-ai-hallucinations/) · [Clearbrief pricing 2026](https://www.aivortex.io/legal/compare/clearbrief-pricing-2026/)
- [Westlaw Edge Quick Check](https://legal.thomsonreuters.com/en/products/westlaw-edge/quick-check)
- [HalluCiteChecker (arXiv)](https://arxiv.org/pdf/2604.26835) · [CiteAudit (arXiv)](https://arxiv.org/pdf/2602.23452)
- [DeepSciVerify — verifying scientific claim–citation alignment (arXiv)](https://arxiv.org/html/2605.27710v1)
- [SciLens — multimodal scientific claim verification (arXiv)](https://arxiv.org/pdf/2606.20873)
- [RIGOURATE — quantifying scientific exaggeration (arXiv)](https://arxiv.org/pdf/2601.04350)
- [Gold label errors in the SciFact benchmark (ACL 2026)](https://aclanthology.org/2026.bionlp-1.9/)

**Statistical consistency checking**
- [GRIM, SPRITE, statcheck: fraud detection (CASRAI)](https://casrai.org/guides/statistical-fraud-detection-grim-sprite-statcheck)
- ["Spell-checker for statistics" reduces errors in psychology (Nature)](https://www.nature.com/articles/d41586-023-00788-6)
- [statcheck (Wikipedia)](https://en.wikipedia.org/wiki/Statcheck)

**Publisher-side screening & market structure**
- [STM Integrity Hub](https://stm-assoc.org/what-we-do/strategic-areas/research-integrity/integrity-hub/)
- [Clear Skies](https://clear-skies.co.uk/solutions/)
- [Signals — detecting invalid references (Jan 2026)](https://research-signals.com/2026/01/13/new_in_signals_jan_2026/) · [Signals for publishers](https://research-signals.com/publishers/)
- [Silverchair ScholarOne Relay integrity integrations](https://www.silverchair.com/news/silverchair-announces-new-research-integrity-integrations-via-scholarone-relay/)
- [Paperpal Preflight for publishers](https://paperpal.com/preflight) · [for editorial desk](https://paperpal.com/preflight-for-editorial-desk)
- [Scholarly publishing trends to watch in 2026 (Scholastica)](https://blog.scholasticahq.com/post/scholarly-publishing-trends-2026/)
- [Peer review time statistics 2026](https://tesify.app/peer-review-time-statistics-2026/)

**LLM-based paper checking & evidence synthesis**
- [The Black Spatula Project](https://the-black-spatula-project.github.io/) · [Steve Newman's write-up](https://secondthoughts.ai/p/the-black-spatula-project)
- [AI tools are spotting errors in research papers](https://slguardian.org/ai-tools-are-spotting-errors-in-research-papers-a-growing-movement/)
- [AI tools for systematic literature reviews (CASRAI)](https://casrai.org/guides/ai-tools-for-systematic-literature-review)
- [AI tools for academic peer review: what they actually check in 2026](https://www.thesify.ai/blog/ai-tools-academic-peer-review)
