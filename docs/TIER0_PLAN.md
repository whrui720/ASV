# Tier 0 — Implementation Plan

**Status:** **implemented** 2026-09-15 (plan written 2026-09-14, from `main` at `bbb7be1`).
The plan below is preserved as written; what actually landed, and where it deviates, is
recorded in [§14](#14-implementation-record) at the end.
**Scope:** how to implement [`VALUE_PROPOSITION.md`](VALUE_PROPOSITION.md) §7 Tier 0 items
**0.1–0.5**, plus **0.6 — reference-existence and retraction checking** (the §5/L1 capability
ASV did not have).

Companion documents: [`VALUE_PROPOSITION.md`](VALUE_PROPOSITION.md) (why),
[`SOURCE_ACQUISITION.md`](SOURCE_ACQUISITION.md) (the acquisition layer this plan touches at
the edges but does not fix — that is Tier 1).

Every number in this document is measured from artifacts in `runs/`; the snippets are in
[Appendix C](#appendix-c--how-the-numbers-in-this-plan-were-computed).

---

## 0. Read this first: Tier 0 makes the tool look worse

Tier 0 is almost entirely subtraction. On the measured corpus it converts **224 "passed"
verdicts into roughly 5–10 evidence-backed verdicts and ~296 honest abstentions.** That is
the point — §2.2 of the value proposition establishes that only 10 of 306 claims ever
received a judgment an evidence passage participated in, so Tier 0 does not destroy value, it
stops concealing the absence of it.

But the consequence has to be stated before any code is written, because it determines how
the work is framed and what ships alongside it:

- The headline number after Tier 0 is **"we could check 10 of your 306 claims."**
- Nothing in Tier 0 raises that number. **Tier 1 (source acquisition) is the only thing that
  does.** Tier 0 is the prerequisite that makes Tier 1's gains measurable and believable.
- Therefore: do not demo Tier 0 alone, and do not ship it to an external user without either
  (a) Tier 1.1/1.2 alongside it, or (b) the §9 "free wedge" framing built into the output —
  *"we checked the N of your M references we could obtain in full text; here are the findings,
  and here are the M−N we could not check, with reasons."*

The one place Tier 0 **adds** output rather than removing it is **0.6**: reference-existence
and retraction checking produce new, positive findings on references ASV cannot otherwise
reach, at zero LLM cost. That is deliberate — it is the only item here that improves the demo
as well as the epistemics.

---

## 1. Dependency graph and PR sequence

Tier 0's five items are not independent. 0.2 is the substrate: 0.1, 0.3, 0.5 and 0.6 each need
somewhere to *write* their outcome, and 0.4's label taxonomy must be identical to the verdict
ontology or the benchmark measures nothing.

```
        P0  spike / calibration  (no product code)
             │
             ▼
        P1  0.2  verdict ontology + models        ◄── blocks everything
             │
     ┌───────┼───────────┬────────────────┬───────────────┐
     ▼       ▼           ▼                ▼               ▼
    P2      P3          P4               P5              P7
   0.1     0.5         0.3              0.6             0.4
 delete  evidence   content-quality  reference       gold set
plausib. invariant      gate         existence      (labelling starts
     │       │           │                │           at P1, ends last)
     └───────┴───────────┴────────────────┘
                         ▼
                        P6  API + frontend surface
                         ▼
                        P8  docs + published metrics
```

| PR | Item | Depends on | Est. | Behaviour change |
|---|---|---|---|---|
| **P0** | Spike: verify free-API contracts; calibrate content-quality thresholds | — | 0.5–1 d | none (scripts only) |
| **P1** | 0.2 verdict ontology, models, compat shim | — | 1–2 d | **none** — every site maps its current outcome onto the new enum |
| **P2** | 0.1 delete the plausibility verdict | P1 | 0.5 d | large (247 claims) |
| **P3** | 0.5 evidence invariant + quote verification | P1 | 1–2 d | medium (12 claims reclassified) |
| **P4** | 0.3 content-quality gate + best-of-N resolution | P1, P0 | 2–3 d | medium (10 batches reclassified) |
| **P5** | 0.6 reference existence + retraction | P1, P0 | 2–3 d | additive |
| **P6** | API read model + frontend | P1–P5 | 1–2 d | UI only |
| **P7** | 0.4 gold set, annotation tool, eval harness | P1 (schema); numbers need P2–P5 frozen | 2–3 d tooling + **6–12 h human labelling** | none (offline) |
| **P8** | Docs: CLAUDE.md, README, published metrics | all | 0.5 d | none |

**P1 is deliberately a no-op PR.** It adds an enum and fields, and makes every existing write
site emit the enum value equivalent to what it emits today, with a test asserting run output
is unchanged modulo the new keys. This earns its own PR because it lets P2–P5 be reviewed as
*purely semantic* diffs: every line that changes a verdict in P2–P5 is a line where someone
decided to stop guessing, and a reviewer can see exactly those lines.

**P7's labelling is the long pole and cannot be compressed.** Start collecting seed pairs the
day P1 merges.

---

## 2. Item 0.2 — Verdict ontology *(the substrate)*

> Replace `passed: bool` with `substantiated` / `partially_substantiated` /
> `not_substantiated` / `contradicted` / `not_checkable(reason_code)`.

### 2.1 Why this cannot be done in the API layer

`apps/api/services/read_model.py:64` already derives a four-value verdict (`passed` /
`failed` / `unresolved_source` / `skipped`) from the raw result files. It is tempting to just
extend that function. **It cannot work**, for three independent reasons:

1. **`contradicted` does not exist anywhere in the data.** Whether the source says the opposite
   or merely fails to mention the claim is known only at judgment time, inside
   `LLMVerifier.verify_claim_against_source` (`llm_verifier.py:86`), which collapses both to
   `passed: false`. No post-hoc function can recover it. `_derive_verdict` is not
   under-implemented; it sits downstream of the information loss.
2. **`not_checkable` has at least eleven distinct causes** (no citation, no URL resolved, fetch
   failed, abstract-only, paywall interstitial, retrieval empty, evidence unverifiable,
   reference not found, reference unverified, unresolvable by design, internal error). The
   reason is what tells a user what to *do*. Nine of the eleven are knowable only at the point
   the failure happens.
3. **0.5's invariant has to be enforced at construction.** A read-model derivation runs after
   the bad data has already been written to `validation_results/*.json`.

So the ontology lives in `src/asv/core/`, the API's `Verdict` literal becomes a pass-through,
and `_derive_verdict` is demoted to a **legacy fallback for run folders written before this
change** (see §9).

### 2.2 New module: `src/asv/core/verdicts.py`

```python
class Verdict(str, Enum):
    SUBSTANTIATED           = "substantiated"
    PARTIALLY_SUBSTANTIATED = "partially_substantiated"
    NOT_SUBSTANTIATED       = "not_substantiated"
    CONTRADICTED            = "contradicted"
    NOT_CHECKABLE           = "not_checkable"

class NotCheckableReason(str, Enum):
    # 0.1 — no source exists to check against
    NO_SOURCE_AVAILABLE    = "no_source_available"      # claim carries no citation
    ORIGINAL_CONTRIBUTION  = "original_contribution"    # paper's own novel finding
    # acquisition
    SOURCE_NOT_RESOLVED    = "source_not_resolved"      # zero candidate URLs
    SOURCE_DOWNLOAD_FAILED = "source_download_failed"   # candidates found, all fetches failed
    # 0.3 — bytes arrived, but they are not judgeable evidence
    ABSTRACT_ONLY          = "abstract_only"
    PAYWALL_INTERSTITIAL   = "paywall_interstitial"
    CONTENT_REJECTED       = "content_rejected"
    # 0.5 — judgment could not be evidenced
    RETRIEVAL_EMPTY        = "retrieval_empty"          # no chunk cleared the threshold
    EVIDENCE_UNVERIFIABLE  = "evidence_unverifiable"    # quotes absent from the source
    # 0.6 — the reference itself
    REFERENCE_NOT_FOUND    = "reference_not_found"
    REFERENCE_UNVERIFIED   = "reference_unverified"
    # catch-alls
    UNRESOLVABLE_BY_DESIGN = "unresolvable_by_design"   # book / personal comm. (Tier 1.6 hook)
    VALIDATION_ERROR       = "validation_error"

ACCUSATION_VERDICTS = {Verdict.NOT_SUBSTANTIATED, Verdict.CONTRADICTED}
EVIDENCED_VERDICTS  = {Verdict.SUBSTANTIATED, Verdict.PARTIALLY_SUBSTANTIATED,
                       Verdict.NOT_SUBSTANTIATED, Verdict.CONTRADICTED}
```

**Why two fields, not a compound `not_checkable(reason)` string.** The memo writes it as one
token. Two orthogonal fields (`verdict`, `not_checkable_reason`) are better because API
faceting (`apps/api/routers/claims.py:19 _compute_facets`) and the frontend filter chips key
off exact values; a compound string would produce 13 verdict facets and make "show me
everything we could not check" impossible without prefix matching. A Pydantic validator
enforces the pairing, so the two fields cannot disagree.

**Why `ACCUSATION_VERDICTS` is a named constant, not a comment.** §10 identifies false
accusation as the critical risk. Making the accusation class first-class means the evidence
invariant (§5), the eval harness (§8.5), and any future "escalate before accusing" policy
(Tier 2.3) all reference one definition.

### 2.3 Changes to `src/asv/core/models.py`

**New model — `EvidenceSpan`** (0.5 uses it; defined here because `ValidationResult`
references it):

```python
class EvidenceSpan(BaseModel):
    quote: str                         # verbatim text from the source
    role: Literal["supporting", "contradicting", "nearest_relevant"]
    source_url: str                    # resolvable; points at what was actually fetched
    retrieval_score: Optional[float] = None
    char_start: Optional[int] = None   # offset into the extracted source text
    char_end: Optional[int] = None
    locator: Optional[str] = None      # best-effort "p. 4" / section heading
    verified_verbatim: bool = False    # did this quote actually appear in the source?
```

**`ValidationResult` (`models.py:68`) — field by field:**

| Field | Change | Why |
|---|---|---|
| `verdict: Verdict` | **new, required** | the ontology |
| `not_checkable_reason: Optional[NotCheckableReason]` | **new** | required iff `verdict == NOT_CHECKABLE`, forbidden otherwise |
| `evidence: List[EvidenceSpan]` | **new** | 0.5 |
| `source_url: Optional[str]` | **new** | 0.5 — a claim row must carry its own resolvable URL; today only `ValidationBatch` has one, and the two `*_uncited_results.json` files have none at all |
| `content_quality: Optional[ContentQuality]` | **new** | 0.3 — mirrored from the batch so a single claim row is self-describing |
| `flags: List[str]` | **new** | orthogonal signals (`cited_source_retracted`, `claimed_original`, …) that must not become verdicts |
| `confidence: float` | → `Optional[float]`, **must be `None` when `verdict == NOT_CHECKABLE`** | a confidence number attached to an abstention is exactly the "confident-looking number with no evidence" §0 attacks |
| `passed: bool` | → **`@computed_field`, derived, deprecated** | see below |
| `validated: bool` | keep, redefine | now "a judgment was attempted against a source"; `False` for every `not_checkable` |
| `validation_method` | keep, change vocabulary | add `"not_checkable"`; retire `"truth_table+llm_check"`, `"truth_table+llm_only"`, `"llm_check"` |
| `sources_used: List[str]` | **deprecated; stop writing quotes into it** | today it holds *quotes* (`process_qualitative.py:39`), a *local dataset path* (`process_quantitative.py:35`), and *fact-check URLs* (`claim_orchestrator.py:338`). Three meanings, one field. Going forward: URLs only; quotes live in `evidence[]` |

**On keeping `passed`.** The memo says "replace". The recommendation here is to **keep it as a
derived, non-settable computed field through Tier 0, then delete it in Tier 1**:

```python
@computed_field  # type: ignore[prop-decorator]
@property
def passed(self) -> bool:
    """DEPRECATED - derived from `verdict`. Read `verdict` instead."""
    return self.verdict == Verdict.SUBSTANTIATED
```

Justification:

- A computed field **cannot disagree with `verdict`**. The failure mode the memo attacks is a
  `passed` set independently of the evidence; a derived `passed` is structurally incapable of
  that. Deleting the field and deriving it anyway are equally safe; only one of them is cheap.
- The mapping is deliberately conservative: `partially_substantiated → False`,
  `not_checkable → False`. A legacy consumer filtering `passed == true` therefore
  **under-counts** rather than over-counts. For a tool whose named failure mode is unearned
  confidence, under-counting is the only acceptable direction to be wrong in.
- Deleting it inside Tier 0 means touching 18 construction sites plus `read_model.py`,
  `run_registry.py:88`, `claim_orchestrator.py:885`, `apps/api/schemas.py:44`, the compare
  page, and 8 historical run folders — for zero epistemic gain. Spend that budget on P2–P5.

**Pydantic mechanics to pin in P1.** `model_config` defaults to `extra="ignore"`, so
`ValidationResult(**legacy_json_containing_passed)` will not raise on the computed field. There
is **no round-trip of `ValidationResult` from JSON anywhere in the codebase today**
(`read_model.py` reads plain dicts; `load_claims_from_json` reconstructs only `ClaimObject`),
so this is latent rather than active — add a test that pins it before someone adds one.

**`ValidationBatch` (`models.py:92`):**

| Field | Change | Why |
|---|---|---|
| `content_quality: Optional[ContentQuality]` | new | 0.3 |
| `judgeable: bool` | new | `download_successful and content_quality == FULL_TEXT`. Keeping "we got bytes" and "the bytes are evidence" separate *is* 0.3 |
| `reference_check: Optional[ReferenceCheck]` | new | 0.6 |
| `download_successful: bool` | keep | still "bytes arrived and cleared the reject floor" |

### 2.4 The P1 mapping table (the no-op PR)

Every existing construction site maps as follows. **No verdict changes meaning in P1**; P2–P5
then change these mappings one at a time.

| Site | Today | P1 verdict | Later changed by |
|---|---|---|---|
| `claim_orchestrator.py:330` uncited qual | `passed = tt or llm` | `SUBSTANTIATED` / `NOT_SUBSTANTIATED` | **P2** → `NOT_CHECKABLE(no_source_available)` |
| `claim_orchestrator.py:382` uncited quant, branch A | same | same | **P2** → branch deleted |
| `claim_orchestrator.py:421` no dataset found | `passed=False, method=source_not_found` | `NOT_CHECKABLE(source_not_resolved)` | — |
| `claim_orchestrator.py:541 / 678 / 804` batch download failed | `passed=False, conf=0.0` | `NOT_CHECKABLE(source_download_failed)` | **P4** splits out `abstract_only` etc. |
| `process_qualitative.py:31` RAG pass | `passed=True` | `SUBSTANTIATED` | **P3** adds `PARTIALLY_*` / `CONTRADICTED` |
| `process_qualitative.py:31` RAG fail | `passed=False` | `NOT_SUBSTANTIATED` | **P3** splits `RETRIEVAL_EMPTY` |
| `process_qualitative.py:51` plausibility fallback | `passed=plausible` | `NOT_CHECKABLE(no_source_available)` | **P2** deletes the branch |
| `process_qualitative.py:65` exception handler | `passed=False` | `NOT_CHECKABLE(validation_error)` | — |
| `process_quantitative.py` script validator | `passed` from script | `SUBSTANTIATED` / `NOT_SUBSTANTIATED` | Tier 4 cuts this path |

Three of these are **already corrections in P1**: `source_not_found`, batch-download failure,
and the exception handler all currently emit `passed: false`, which reads as *"this claim is
wrong"* when it means *"we never checked it."* Those fixes are free and uncontroversial, and
they land with the no-op PR. On the measured run that is **41 claims** (4 + 37) that stop
being reported as failed claims.

---

## 3. Item 0.1 — Delete the plausibility verdict

> Uncited claims get `status: not_checkable`, `reason: no_source_available`. No `passed`, no
> `confidence`.

### 3.1 Every place the plausibility path lives

Measured: **247 of 306 claims (81%)** take this path; **217 of 224 passes (97%)** come from it.

| # | Location | What it does | Action |
|---|---|---|---|
| 1 | `claim_orchestrator.py:314` `_process_uncited_qualitative` | `TruthTableChecker` + `LLMVerifier.verify_claim`; `passed = tt.found or llm.plausible`; `confidence = max(...)` | **rewrite** — 233 claims |
| 2 | `claim_orchestrator.py:365-395` `_process_uncited_quantitative` branch A | same two calls; **also gates whether `DatasetFinder` runs at all** | **delete the branch** — 10 claims |
| 3 | `process_qualitative.py:50-58` | `if source_text` is falsy → `verify_claim` fallback | **delete the branch** |
| 4 | `llm_verifier.py:25-81` `verify_claim` + `_build_verification_prompt` | the plausibility primitive itself | **delete both methods** |
| 5 | `validator/truth_table_checker.py` (152 lines) + `claim_orchestrator.py:74` | Google Fact Check API | **remove call sites; delete module** |

**Site 3 is currently unreachable but must still go.** Both `_process_cited_qualitative`
(`:804`) and `_process_paper_backed_quant` (`:678`) `continue` on `download_successful == False`
before ever calling `validate_claim`, so the fallback never fires today. It is nonetheless a
loaded gun: it is one refactor away from firing, and CLAUDE.md already asserts to readers that
"an empty/paywalled source cannot produce a fake `llm_check` pass." Keeping dead code that
contradicts the documented invariant is worse than either deleting it or documenting it
honestly. Delete it, and let `source_text` become a required non-empty argument so the
condition cannot be reintroduced silently.

**On `TruthTableChecker`.** Those two call sites are its *only* ones (verified by grep across
`src`, `apps`, `scripts`). After P2 it is dead code that holds an API key and makes network
calls. Tier 4 lists it for removal anyway, and the memo notes it currently writes `"No API key
configured"` into **233 user-facing explanation strings**. Recommendation: remove the calls and
`self.truth_table` in P2, delete `validator/truth_table_checker.py` and its
`validator/__init__.py` export in the same PR, and update `docs/QUICKSTART.md:342-345` and
`src/asv/validator/README.md:20` which reference it. `GOOGLE_FACT_CHECK_API_KEY` stays in
`.env.example` as a no-op for one release, then goes.

### 3.2 What an uncited claim produces instead

```python
ValidationResult(
    claim_id=claim.claim_id,
    claim_type=claim.claim_type,
    originally_uncited=False,
    validated=False,
    validation_method="not_checkable",
    verdict=Verdict.NOT_CHECKABLE,
    not_checkable_reason=NotCheckableReason.NO_SOURCE_AVAILABLE,
    confidence=None,
    explanation=(
        "No citation was attached to this claim in the source document, so there is no "
        "source to check it against. ASV does not judge claims from model priors."
    ),
    evidence=[],
    sources_used=[],
    flags=["claimed_original"] if claim.is_original else [],
)
```

**Split out `is_original`.** §2.4(b) shows 25 `is_original` claims routed to plausibility, 22
"passing" — a validator whose confidence tracks conformity-to-consensus is anti-correlated
with the thing science values. Under 0.1 these get
`not_checkable_reason=ORIGINAL_CONTRIBUTION` instead of `NO_SOURCE_AVAILABLE`, because "the
paper's own novel finding" and "we could not find the source" are different things a reviewer
wants separated. Caveat to carry into the UI copy: §2.4(b) also records that the `is_original`
classifier **misfires badly** on review papers, so the label must read *"the authoring paper
presents this as its own contribution"*, never *"this is original."* That is why it is also
mirrored into `flags`, which are explicitly non-authoritative.

### 3.3 The uncited-quantitative branch

Removing the plausibility gate at `:365` means every uncited-quantitative claim now reaches
`DatasetFinder`, where previously 10 of 14 were short-circuited. Consequences:

- +10 `DatasetFinder` searches per run of this shape (data.gov CKAN + Kaggle). Negligible cost,
  no LLM.
- Failure now produces `NOT_CHECKABLE(source_not_resolved)` rather than a `passed: false` that
  looks like a failed claim.
- **Do not** add a `DatasetFinder` kill switch here. Tier 4 argues for retargeting or cutting
  `DatasetFinder` wholesale; doing it inside 0.1 mixes two decisions in one diff. Keep 0.1 to
  deletion of the *verdict*, and leave the acquisition question to Tier 4.

### 3.4 Should the LLM opinion survive as a non-evidentiary note?

The memo allows it ("if at all"). **Recommendation: no, default off.**

- It costs one `gemini-2.5-flash-lite` call per uncited claim — 247 calls, the bulk of the run's
  LLM spend — for output that by construction cannot enter a verdict.
- It is a re-entry vector. Any future summary, sort, or export that reaches for a number will
  find one.
- If it must exist, it goes behind `ASV_ADVISORY_NOTES=1` (default off), into
  `advisory_note: Optional[str]` with `advisory_source: "llm_prior"` — **never** into
  `explanation`, **never** with a number, and excluded from every aggregate the API computes.

Removing the calls is also the single largest cost reduction in Tier 0.

---

## 4. Item 0.3 — Content-quality gate

> Classify every fetch as `full_text` / `abstract_only` / `paywall_interstitial` / `rejected`;
> refuse to judge on `abstract_only`; raise the HTML floor from 200 chars to a structure test.

### 4.1 The measured problem

In `runs/hsv_cancer__20260706_192057`, 16 of 51 batches downloaded successfully. Winning hosts:

| Host | Batches | What it actually is |
|---|---|---|
| `www.nature.com` | 9 | landing page: abstract + reference list |
| `europepmc.org` | 3 | genuine full text |
| `link.springer.com` | 1 | landing page / subscription preview |
| `www.annualreviews.org` | 1 | landing page |
| `doi.org` | 1 | whatever the DOI resolved to |
| `scholar.googleusercontent.com` | 1 | scraped PDF |

**10 of 16 "wins" are publisher landing pages.** They clear the 200-char floor easily — a
Nature landing page carries an abstract plus 40–80 references, several thousand characters —
and RAG then searches a document that cannot contain the evidence. Of the 12 claims that
returned "No relevant chunks found", most are against exactly these pages.

### 4.2 New module: `src/asv/sourcefinder/content_quality.py`

```python
class ContentQuality(str, Enum):
    FULL_TEXT            = "full_text"
    ABSTRACT_ONLY        = "abstract_only"
    PAYWALL_INTERSTITIAL = "paywall_interstitial"
    REJECTED             = "rejected"

@dataclass(frozen=True)
class ContentAssessment:
    quality: ContentQuality
    reason: str
    signals: dict   # every value the classifier looked at — auditable, persisted
```

**The classifier must be deterministic and LLM-free.** §5/L4's lesson is that statcheck is
trusted precisely because it abstains deterministically wherever it cannot be certain. A gate
whose job is to decide whether evidence is admissible must not itself be a probabilistic
judgment, and it must be explainable in one line to a user who disagrees with it.

Signals, in order of discriminative power:

1. **IMRaD structure test.** Count standalone headings matching
   `introduction|background`, `materials? and methods|methods|methodology`, `results`,
   `discussion`, `conclusions?`, `acknowledg`. A research article has ≥2; a landing page has
   none — it has *Abstract*, *References*, *Similar content being viewed by others*, *Author
   information*. **This is what "a structure test" means in the memo**, and it is the single
   strongest discriminator.
2. **Paywall phrases.** Highly stable, publisher-specific strings: `"This is a preview of
   subscription content"` (Springer), `"access through your institution"`, `"Buy this article"`,
   `"Subscribe to this journal"`, `"Rent or Buy article"`, `"Get full journal access"`,
   `"immediate online access to all issues"`, `"Sign in to read the full article"`,
   `"Add to cart"`, plus a price regex `(?:US ?\$|\$|€|£)\s?\d{1,3}[.,]\d{2}`.
3. **Reference-list dominance.** Fraction of lines matching `^\s*\d+\.?\s+\S+.*\b(19|20)\d{2}\b`.
   A landing page is mostly its own bibliography; a full text is not.
4. **Abstract-only markers.** An `Abstract` heading with < ~1.5k chars before the next
   references/bibliography marker, and no IMRaD hit.
5. **Usable length** — kept, but *never used alone*. It is what lets the current gate through.
6. **PDF page count.** `_extract_pdf_text` currently discards it; capture it from `fitz`
   (`doc.page_count`) and thread it into the assessment. A 1–2 page PDF with an `Abstract`
   heading is abstract-only; a "Access Denied" PDF is a paywall interstitial.

**Decision order** (thresholds are placeholders — §4.5 calibrates them):

```
usable_chars < 200                                   -> REJECTED
paywall phrase hit and usable_chars < 8000           -> PAYWALL_INTERSTITIAL
imrad_headings >= 2 and usable_chars >= 6000         -> FULL_TEXT
reference_line_fraction > 0.5 and imrad_headings < 2 -> ABSTRACT_ONLY
usable_chars < 4000                                  -> ABSTRACT_ONLY
otherwise                                            -> ABSTRACT_ONLY   # conservative default
```

**The default must be the abstaining class.** An unknown page that is really full text becomes
a false abstention: costly, safe, visible in the metrics as a lower checkable rate. An unknown
landing page classified `full_text` becomes a false accusation: the risk §10 rates *critical*.
Bias hard toward abstention, then use the gold set (§8) to buy the threshold back.

### 4.3 Where it is enforced

`TextDownloader._process_bytes` (`text_downloader.py:75`) is the single choke point — both the
`requests` path (`download`, `:51`) and the Playwright browser path (`download_with_resolution`
step 4, `:430`) route through it. Changes:

- Run the assessment after text extraction; return `content_quality` and `content_signals` in
  the result dict.
- `downloaded` stays `True` for `ABSTRACT_ONLY` and `PAYWALL_INTERSTITIAL` — we did get bytes,
  and the manifest should record precisely what we got. Add `judgeable: bool`.
- `REJECTED` keeps today's behaviour exactly: delete the file, `downloaded=False`, so the
  cascade continues. The existing `_MIN_USABLE_TEXT_CHARS = 200` becomes the `REJECTED` floor
  and nothing more.

### 4.4 The rewrite this forces: `download_with_resolution` becomes best-of-N

**This is the one genuinely invasive change in 0.3 and it needs its justification stated.**

`download_with_resolution` (`text_downloader.py:327`) returns on the **first** candidate with
`downloaded=True` (`:377`, `:385`, `:420`, `:457`). If 0.3 lands without changing that, the
sequence for a typical Nature batch becomes:

1. Candidate 1 = Nature landing page → fetch succeeds → `downloaded=True` → **return**.
2. Orchestrator sees `abstract_only` → refuses to judge → `not_checkable(abstract_only)`.
3. Candidate 2 = the Europe PMC mirror, which *is* full text, **is never tried.**

So 0.3 alone would convert a fake pass into an abstention while leaving a real full text
untouched on the table — strictly worse than either the status quo or the correct version.
`download_with_resolution` must therefore iterate the candidate list keeping the **best**
result rather than the first:

```
best = None
for url in candidates[:MAX_CANDIDATES_PER_BATCH]:      # cap, default 6
    r = self.download(url, citation_id)
    record_attempt(url, source_label, r)
    if not r["downloaded"]:
        continue
    if better(r["content_quality"], best):             # FULL_TEXT > ABSTRACT_ONLY >
        replace_best(r)                                # PAYWALL_INTERSTITIAL > REJECTED
    if r["content_quality"] is FULL_TEXT:
        break                                          # early exit: nothing beats full text
return best or failure
```

Notes:
- **Disk hygiene:** each candidate writes `citation_{id}_text.{fmt}`, which collides across
  candidates for the same citation. Use `citation_{id}_cand{n}_text.{fmt}` while iterating and
  delete every non-winner before returning, so the existing post-batch cleanup and
  `SourceManifest.mark_deleted` semantics are unaffected.
- **Cost:** `SOURCE_ACQUISITION.md` measures that 32/51 batches have exactly **one** candidate,
  so the real increase is small; the cap bounds the worst case.
- **Relationship to Tier 1.1:** this is a *partial* pre-implementation of union-then-rank. Keep
  it minimal — do **not** restructure `AcademicPaperFinder.find_urls` here (that is Tier 1.1's
  job). 0.3 changes only the consumption of the candidate list, not its construction.
- `ResolutionAttempt` (`models.py:84`) gains `content_quality: Optional[ContentQuality]` so the
  manifest records the quality of every attempt, not just the winner. That turns
  `text_sources/_manifest.json` into the calibration dataset for future threshold work.

### 4.5 Calibration (must precede P4 — this is P0's second half)

The thresholds above are guesses and must not ship as guesses. **Problem: the evidence is
already deleted.** `_KEEP_SOURCES` is off by default (`claim_orchestrator.py:35`), so
`runs/*/text_sources/` contains only `_manifest.json`.

`scripts/calibrate_content_quality.py`:

1. Read `winning_url` and every `resolution_attempts[].url` from all 8 run folders'
   `text_sources/_manifest.json`.
2. Re-fetch each, politely (per-host token bucket, ≥1 s between same-host requests), into a
   local cache keyed by URL sha256 so the script is re-runnable offline.
3. Run extraction + the classifier; emit
   `calibration/content_quality.csv` with `url, host, format, usable_chars, imrad_hits,
   ref_line_fraction, paywall_hits, page_count, predicted_quality`.
4. **Hand-label the ~60 distinct URLs** (≈30 min: open, eyeball, type one letter). Store as
   `calibration/content_quality.labels.csv`.
5. `pytest` fixture asserts the classifier reproduces the hand labels with **zero
   `abstract_only → full_text` errors** (the unsafe direction) and ≤15% `full_text →
   abstract_only` (the safe direction).

Also set `ASV_KEEP_SOURCES=1` for all development runs from here on, and say so in CLAUDE.md.

### 4.6 Orchestrator consequences

In `_process_cited_qualitative` (`:750`) and `_process_paper_backed_quant` (`:613`), the
`if not download_result['downloaded']` guard becomes a three-way branch:

| Outcome | Batch fields | Per-claim verdict | RAG called? |
|---|---|---|---|
| no bytes | `download_successful=False, judgeable=False` | `NOT_CHECKABLE(source_download_failed` or `source_not_resolved)` | no |
| bytes, not full text | `download_successful=True, judgeable=False, content_quality=…` | `NOT_CHECKABLE(abstract_only` / `paywall_interstitial)` | **no** |
| full text | `download_successful=True, judgeable=True` | RAG decides | yes |

The middle row is a **cost saving**: ~10 batches per run stop making LLM calls entirely.

---

## 5. Item 0.5 — Never emit a verdict without a quoted span and a resolvable URL

> Makes every finding checkable by a human in ten seconds.

### 5.1 Enforce it as a model invariant, not a convention

In `ValidationResult`:

```python
@model_validator(mode="after")
def _evidence_required_for_judgments(self) -> "ValidationResult":
    if self.verdict in EVIDENCED_VERDICTS:
        if not self.evidence:
            raise ValueError(
                f"{self.claim_id}: verdict={self.verdict} requires >=1 EvidenceSpan"
            )
        if not any(e.verified_verbatim for e in self.evidence):
            raise ValueError(
                f"{self.claim_id}: verdict={self.verdict} requires >=1 verbatim-verified span"
            )
        if not self.source_url:
            raise ValueError(f"{self.claim_id}: verdict={self.verdict} requires a source_url")
    if self.verdict is Verdict.NOT_CHECKABLE:
        if self.not_checkable_reason is None:
            raise ValueError(f"{self.claim_id}: not_checkable requires a reason code")
        if self.confidence is not None:
            raise ValueError(f"{self.claim_id}: not_checkable must not carry a confidence")
    elif self.not_checkable_reason is not None:
        raise ValueError(f"{self.claim_id}: reason code set on a non-abstention verdict")
    return self
```

**Justification for putting this in `models.py` rather than a review checklist.** §0's
diagnosis is that the system "manufactures a confident-looking number with no evidence behind
it." A convention prevents that until the next contributor; a constructor invariant makes the
state **unrepresentable**. Any code path that tries to emit an unevidenced judgment fails
loudly at construction, in tests, before a user ever sees it. This is the highest-leverage
twenty lines in the plan.

### 5.2 `not_substantiated` also requires evidence — and that is the point

The obvious objection: what quote do you attach when the source simply does not discuss the
claim? Answer: **the passages that were the closest match.** *"Here is the most relevant thing
in the cited source, and it does not say this"* is exactly the ten-second-checkable artefact
0.5 asks for, and it is what distinguishes a finding a reviewer can act on from *"not
supported, confidence 0.31"*. Hence `EvidenceSpan.role = "nearest_relevant"`.

### 5.3 The invariant forces the Tier 2.4 fix into Tier 0

`llm_verifier.py:99-106` returns `passed=False, confidence=0.0, explanation="No relevant
chunks found in source"` when nothing clears `RAG_SIMILARITY_THRESHOLD` (0.15). That hit **12 of
22** successfully-downloaded claims in the measured run and was reported as a failed claim.

Under 0.5 there is no span to attach, so the state is unconstructible: it **must** become
`NOT_CHECKABLE(retrieval_empty)`. This is Tier 2.4's insight arriving early as a mechanical
consequence rather than as scope creep, and it is worth calling out to reviewers.

Keep the slice minimal: **reclassify only.** Do not build hybrid retrieval, section-aware
chunking, or embeddings — those are Tier 2.1.

### 5.4 Verify the quotes are real

The LLM returns `supporting_quotes` (`llm_verifier.py:122`) and can fabricate them. §2.4(c)
documents this system already inventing its own evidence once (`required_cols =
['attachment_time_minutes', 'penetration_time_minutes']` — columns that did not exist). An
unverified quote is the same failure in the RAG path, and it destroys 0.5's entire value.

Verification procedure, in `LLMVerifier` after the response parses:

1. Normalize both sides: Unicode NFKC, collapse whitespace, lowercase, strip smart quotes and
   soft hyphens (PDF extraction produces all three).
2. Search for the quote **within the retrieved chunks that were handed to the model**, not the
   whole document. If the model quotes something outside its own context window, it did not
   read it there.
3. Exact substring first; on miss, `rapidfuzz.fuzz.partial_ratio >= 92`. **`rapidfuzz==3.11.0`
   is already declared in `pyproject.toml:39` and currently imported nowhere — zero new
   dependency.**
4. Set `verified_verbatim`; record `char_start`/`char_end` from the match offset mapped back
   into the source text.
5. If **no** quote verifies → downgrade to `NOT_CHECKABLE(evidence_unverifiable)` and log the
   unverifiable quotes into `validation_metadata` for debugging. Do not silently keep the
   verdict.

### 5.5 Resolvable source URL

`ValidationResult.source_url` is populated from the batch's `winning_url` in all three cited
paths. "Resolvable" is satisfied by construction — we fetched it moments earlier. Also persist
`source_fetched_at` and `content_quality` on the result so a reader can tell *what* was
fetched, not just *from where*.

For 0.6, when a canonical DOI has been recovered, prefer `https://doi.org/{doi}` as the
human-facing `source_url` and keep the actual fetched URL in
`validation_metadata["fetched_url"]` — DOIs stay resolvable after publishers reorganize.

### 5.6 Prompt change

`_build_source_verification_prompt` (`llm_verifier.py:203`) currently asks for
`{passed, confidence, explanation, supporting_quotes}`. It becomes:

```jsonc
{
  "verdict": "substantiated | partially_substantiated | not_substantiated | contradicted",
  "confidence": 0.0,
  "explanation": "…",
  "quotes": [{"text": "verbatim span copied from an excerpt", "role": "supporting|contradicting|nearest_relevant"}]
}
```

with instructions that quotes must be **copied verbatim from the excerpts, never paraphrased
or reconstructed**, that `contradicted` requires a quote whose `role` is `contradicting`, and
that `partially_substantiated` is the correct answer when the source supports a weaker version
of the claim (which is the hook §6's M1/M2 detectors will later hang off). Bump
`LLM_TASK_CONFIG["source_grounded_verification"]` with a `prompt_version` string, recorded on
every result — §10 names LLM nondeterminism undermining the audit trail as a medium risk, and
recording model + prompt version is the stated mitigation.

---

## 6. Item 0.6 (new) — Does the reference even exist? Plus: is it retracted?

> §5/L1: *"solved, free, table stakes. **ASV does not currently do it** — it goes straight to
> full-text acquisition. Ship existence + retraction checking, never charge for it, and use it
> as the free tier."*

### 6.1 Why this belongs in Tier 0 and not later

1. **It is a precondition for every other verdict.** If reference [34] does not exist, every
   claim citing it is unjudgeable — and *that is a finding*, the most serious one the tool can
   produce, not an abstention that looks like a shrug.
2. **It fixes a Tier-0-shaped lie.** Today a fabricated reference and a Wiley 403 produce
   identical output: `download_successful: false`. That is exactly the "paywalled and
   contradicted are the same output" defect 0.2 exists to fix, one layer up.
3. **It is free.** Keyless HTTP APIs, no LLM beyond the citation parse that
   `AcademicPaperFinder._parse_citation_with_llm` already performs and caches.
4. **It pays for itself in acquisition yield.** See §6.7 — it hands `AcademicPaperFinder` a DOI
   it currently only discovers as a last resort.
5. **It is the only part of Tier 0 that adds visible output.** See §0.

### 6.2 The corpus makes this harder than it sounds

Measured over the 253 references in `hsv_cancer.pdf`:

- **0 references contain an inline DOI.** Every DOI-based shortcut is unavailable. Matching
  must be metadata-based.
- Bibliography strings are mangled by PDF extraction: `Harrison<?>s Principles`,
  `tegument<?>capsid`, and missing spaces at field boundaries — `J Virol1999; 73`,
  `AdvExpMedBiol1994`. Naive tokenization will mis-parse journal and year.
- Year range 1904–2068 (the 2068 is an extraction artefact, itself a useful signal), 1 reference
  pre-1970, ≥2 book/chapter references — including reference **[1]**, a chapter in *Harrison's
  Principles of Internal Medicine*. **That single reference is the canonical false positive:**
  it is real, it is fine, and it is not in Crossref. Any design that reports it as "not found"
  is broken.

### 6.3 Free APIs to use

All keyless or email-only; all permit this use. **Endpoint contracts must be confirmed in P0
before any of this is coded** — see §6.8.

| Service | Use | Auth | Notes |
|---|---|---|---|
| **Crossref** `/works?query.bibliographic=` and `/works/{doi}` | primary metadata match | none; `mailto=` → polite pool | ~160M records; already used at `academic_paper_finder.py:228` for DOI recovery |
| **OpenAlex** `/works?filter=doi:` / `?search=` / `?filter=title.search:` | primary title match | none; `mailto=` → polite pool | ~250M works, best recall incl. non-Crossref; **also carries `is_retracted`** |
| **Europe PMC** `/europepmc/webservices/rest/search` | biomedical match | none | 40M+, includes PubMed + preprints; exposes retraction/EoC in the record |
| **PubMed E-utilities** `esearch` / `ecitmatch` | exact citation match | optional key (3→10 rps) | `ecitmatch` takes `journal|year|volume|firstpage|author|key` and is *purpose-built* for this |
| **DataCite** `/dois?query=` | datasets, software, theses | none | catches non-article references |
| **Semantic Scholar** | tertiary confirmation | optional key | already wired; shared pool 429s under load |
| **Crossref Retraction Watch data** | retraction status | none | Crossref distributes the Retraction Watch DB free; also surfaced per-DOI via `update-to` relations of `type: retraction` |

Use **Crossref + OpenAlex** as the always-on pair (discipline-agnostic), add **Europe PMC +
PubMed** when the reference looks biomedical or the first pair misses, and **DataCite** when
the parsed type is dataset/software/thesis.

### 6.4 New module: `src/asv/sourcefinder/reference_verifier.py`

```python
class ReferenceStatus(str, Enum):
    VERIFIED             = "verified"               # confident index match
    AMBIGUOUS            = "ambiguous"              # near match, not confident
    NOT_FOUND_IN_INDEXES = "not_found_in_indexes"   # NOT "fabricated"
    UNINDEXED_BY_DESIGN  = "unindexed_by_design"    # book, chapter, personal comm., pre-1970
    UNVERIFIED           = "unverified"             # APIs failed / rate-limited — not a finding

class RetractionStatus(str, Enum):
    NONE = "none"; RETRACTED = "retracted"
    CONCERN_RAISED = "concern_raised"               # expression of concern
    CORRECTED = "corrected"; UNKNOWN = "unknown"

class ReferenceCheck(BaseModel):
    citation_id: str
    raw_citation_text: str
    parsed: dict                      # title/author/year/journal/volume/pages/type/doi
    status: ReferenceStatus
    matched_doi: Optional[str] = None
    matched_title: Optional[str] = None
    matched_url: Optional[str] = None       # canonical https://doi.org/... when available
    match_score: Optional[float] = None
    near_miss: Optional[dict] = None        # best candidate even when rejected
    indexes_queried:   List[str] = []
    indexes_responded: List[str] = []       # responded != queried is the whole UNVERIFIED story
    retraction_status: RetractionStatus = RetractionStatus.UNKNOWN
    retraction_notice_url: Optional[str] = None
    checked_at: str
```

### 6.5 Algorithm

```
0. parse   -> reuse AcademicPaperFinder._parse_citation_with_llm (already cached per string)
1. if doi  -> Crossref /works/{doi};  200 => VERIFIED, score 1.0
2. else    -> query Crossref bibliographic, OpenAlex title.search,
              Europe PMC, PubMed ecitmatch (only when journal+year+volume+firstpage present)
3. score every candidate:
       title_sim    = rapidfuzz.token_set_ratio(norm(parsed.title), norm(cand.title)) / 100
       author_match = parsed.first_author surname in candidate surnames
       year_match   = abs(parsed.year - cand.year) <= 1     # publication-year drift is real
       journal_sim  = abbreviation-tolerant prefix match ("J Virol" ~ "Journal of Virology")
4. decide:
       VERIFIED             title_sim >= 0.90 and (author_match or year_match)
       AMBIGUOUS            0.70 <= title_sim < 0.90, or title hit but author AND year disagree
       NOT_FOUND_IN_INDEXES best title_sim < 0.70   AND  >= 2 indexes responded
       UNINDEXED_BY_DESIGN  parsed.type in {book, chapter, personal_communication, thesis,
                                            report, webpage-without-doi} or year < 1970
       UNVERIFIED           fewer than 2 indexes responded
5. retraction (only when a DOI or PMID was recovered):
       Crossref /works/{doi} -> update-to[] where type == "retraction"
       OpenAlex work.is_retracted
       Europe PMC / PubMed publication-type flags
```

### 6.6 False-accusation controls — mandatory, not optional

Saying *"this reference does not exist"* about a real reference is an allegation of
fabrication. It is the single worst output this tool can emit. Every one of these is a
requirement, not a nice-to-have:

| Control | Rule |
|---|---|
| **Never claim non-existence** | The user-facing string is *"Not found in Crossref, OpenAlex, Europe PMC or PubMed"*, with the list of indexes actually queried. The enum is `NOT_FOUND_IN_INDEXES`. The words *fabricated*, *hallucinated*, and *fake* appear nowhere in the code or the UI |
| **Two-index quorum** | `NOT_FOUND_IN_INDEXES` requires **≥2 indexes to have responded successfully**. Otherwise `UNVERIFIED`. An API outage must never read as an accusation |
| **Type routing first** | Books, chapters, conference abstracts, theses, government reports, personal communications and pre-1970 work are systematically under-indexed → `UNINDEXED_BY_DESIGN`. Reference [1] of the test corpus (a *Harrison's* chapter) is the regression test for this |
| **Always show the near miss** | Even when rejecting, report the best candidate and its score, so a human sees *"it found the right paper, my year was wrong"* in ten seconds. Same philosophy as 0.5 |
| **Separate from the claim verdict** | A nonexistent reference says nothing about whether the claim is true. `ReferenceCheck` is its own object on the batch; claims get `not_checkable(reference_not_found)` |
| **Measure it** | Hand-label existence for all 253 references of the test corpus (~15 s each ≈ 1 h) and require **zero false `NOT_FOUND_IN_INDEXES`** before the status is shown in the UI |

The parse step must be extended to return `type` and `volume`/`pages`. That is a change to the
shared prompt at `academic_paper_finder.py:196` — justified because (a) it costs ~0 extra
tokens on a call that already happens and is cached, (b) `volume`+`firstpage` unlock PubMed
`ecitmatch`, which is exact rather than fuzzy, and (c) `type` delivers Tier 1.6's
`unresolvable_by_design` for free and prevents the most likely class of false "not found".

### 6.7 Where it runs, and the free side-benefit

New **stage 0.5** in `ClaimOrchestrator.process_claims`, after `_setup_browser_searcher`
(`:105`) and before step 1:

```python
self.reference_checks = self.reference_verifier.verify_all(citations)   # dict[cid, ReferenceCheck]
self.events.emit("reference_audit_finished", **counts)
```

- Runs over **all** `citations`, not only the ~51 with claims attached. A complete bibliography
  audit is itself the §9 free-wedge deliverable, and *"reference 34 exists but is cited nowhere"*
  is a finding a reviewer wants. 253 refs × 2–4 requests ≈ 700 calls ≈ 3–5 min with polite
  rate limiting, zero LLM cost beyond the already-cached parse.
- Persist to `runs/{run}/sourcefinder/reference_checks.json`; add
  `RunPaths.reference_checks_json()` alongside the existing accessors
  (`run_paths.py:99-125`).
- Persistent cache keyed by `sha256(normalized_citation_string)` under
  `runs/../_refcheck_cache.json` or `~/.cache/asv/refcheck/`, so re-runs on the same PDF cost
  nothing. This is a small down-payment on Tier 1.4.
- Per-host token bucket and `User-Agent` with a contact address (Crossref and OpenAlex polite
  pools both key off `mailto`; `UNPAYWALL_EMAIL` is already collected and is the obvious value
  to reuse).

**The side-benefit, which is large.** `SOURCE_ACQUISITION.md` measures that **32 of 51 batches
have exactly one candidate URL**, and `find_urls` only reaches CrossRef bibliographic DOI
recovery at step 3b, *after* Unpaywall/Semantic-Scholar/regex have all failed
(`academic_paper_finder.py:107-136`). With stage 0.5 running first, every batch whose reference
verifies arrives at resolution **with a DOI already in hand**, so `_resolve_from_doi` (Unpaywall
+ SS + CrossRef union) runs on the *first* try instead of the last. Pass the verified DOI into
`CitationDetails.doi` before `_process_cited_*` runs. On a corpus with zero inline DOIs this
should be the largest single acquisition improvement available before Tier 1 proper — **and it
must be measured**, by diffing batch download rates on `hsv_cancer.pdf` before and after P5.

### 6.8 P0 spike — do this before writing any of §6

My knowledge of these endpoints predates this repository's own timeline, and free scholarly
APIs change. `scripts/probe_existence_apis.py` takes 5 known references (one with a DOI, one
Nature paper, one Europe PMC paper, the *Harrison's* chapter, one deliberately fabricated
title) and, for each service, prints the request URL, status, rate-limit headers, and the exact
JSON path of title/authors/year/DOI/retraction fields. Output is a short markdown table
committed to `docs/` and referenced by the implementation. **Do not code the matcher against
remembered field names.**

### 6.9 Retraction handling

A retracted source does **not** change the claim verdict — a retracted paper can still literally
contain the sentence, and substantiation is a separate question from validity. It raises flags:

- `ValidationResult.flags += ["cited_source_retracted"]` / `["cited_source_concern_raised"]`
- `ValidationBatch.reference_check.retraction_status`
- run summary: `reference_audit.retracted` count, surfaced on the run overview

This matches §5/L1: *"Retraction checking is a distinct and separately valuable signal."* It is
also the highest-value-per-line item in the entire plan for a real user — citing retracted work
is embarrassing, common, and trivially detectable.

---

## 7. Item 0.4 — The gold set *(what is manual, what is not)*

> 200–300 hand-labelled claim–source pairs across ≥3 fields, including hard negatives. Publish
> precision, recall, and false-accusation rate with a calibration curve.

The user's instinct is right: **the labelling is irreducibly manual.** Everything around it is
software, and building that software is what makes 250 labels affordable instead of a
month-long slog. Split precisely:

| Part | Manual? | Effort |
|---|---|---|
| 7.1 Schema + storage | code | 0.5 d |
| 7.2 Seed collection | code | 0.5 d |
| 7.3 Hard-negative generation | **LLM-proposed, human-accepted** | 0.5 d code + 2 h review |
| 7.4 Annotation UI | code | 1–1.5 d |
| 7.5 Eval harness + metrics | code | 1 d |
| **Labelling itself** | **100% human** | **6–12 h**, plus 20% double-annotation |

### 7.1 Schema and storage — `benchmarks/gold/*.jsonl`

```jsonc
{
  "pair_id": "asv-gold-0001",
  "field": "virology",                      // >= 3 fields required
  "provenance": "asv_run|scifact|scitance|citeme|seeded_negative",
  "claim_text": "...",
  "claim_id": "2_5",                        // when sourced from an ASV run
  "source": {"doi": "10.…", "url": "https://doi.org/…",
             "content_quality": "full_text", "text_sha256": "…"},
  "label": "substantiated|partially_substantiated|not_substantiated|contradicted|not_checkable",
  "label_reason": "…",
  "evidence_spans": [{"quote": "…", "char_start": 1024, "char_end": 1180}],
  "miscitation_types": ["M2", "M4"],        // §6 taxonomy — free to record now, pays off at Tier 2.5
  "difficulty": "easy|hard",
  "is_seeded_negative": false,
  "annotator": "AB", "annotated_at": "…", "adjudicated_by": null
}
```

**Labels must be the 0.2 enum verbatim.** This is why 0.4's schema blocks on P1: a benchmark
whose label space differs from the system's output space measures nothing.

**Frozen source snapshots.** A gold pair is worthless if the source 403s or changes next month.
Store the *extracted text* (never the publisher PDF) at `benchmarks/sources/{sha256}.txt`, with
the sha in the record. Redistribution rules, applied per source:

- **Open access (CC-BY / PMC OA subset / arXiv / bioRxiv):** store full extracted text.
- **Everything else:** store **only the excerpt window** needed for the label (the retrieved
  chunks ± a paragraph) plus the sha256 of the full text. This keeps the benchmark reproducible
  without redistributing paywalled full text.
- **Seeded corpora (SciFact, SCitance, CiteME):** store identifiers plus a downloader script;
  **verify each licence before vendoring anything.** Do not assume.

~250 pairs × ~60 KB ≈ 15 MB of text. Acceptable in-repo; if it grows, move to git-lfs rather
than to an external bucket, because reproducibility is the point.

### 7.2 Seed collection — `scripts/build_gold_seed.py`

1. **From ASV's own runs.** Every claim in an existing run folder whose batch downloaded
   successfully is a candidate pair, pre-populated with the retrieved chunks. The measured run
   yields 22 immediately (10 with a substantive judgment). Re-running with Tier 1 acquisition
   fixes will yield far more — so the seeder must be re-runnable and de-duplicating.
2. **From public corpora.** SciFact, SCitance, CiteME. The memo warns a 2026 audit found **5.3%
   gold-label errors in SciFact's dev set** — so every imported pair must be re-labelled by a
   human in the same UI, with the imported label shown only *after* the annotator commits
   theirs (blind-then-reveal). Disagreements are themselves a useful artefact.
3. **≥3 fields.** The existing corpus is virology. Pull at least two more — the cheapest honest
   route is arXiv/bioRxiv OA papers in a different domain (e.g. epidemiology and economics or
   materials science), where full text is freely and legally obtainable, which keeps the gold
   set from silently measuring only "papers ASV can currently download."

### 7.3 Hard negatives — generate them, do not hunt for them

This is the insight that makes the 200–300 target tractable. Naturally occurring miscitations
are ~1 in 6 and expensive to find; **seeded corruption** produces them on demand, and directly
serves §8's "recall on seeded errors" metric and §6's M1–M7 taxonomy.

Take a verified `substantiated` pair and mutate the *claim* along one taxonomy axis:

| Type | Mutation | Target label |
|---|---|---|
| M1 generalization drift | mice → humans; one cohort → "globally" | `not_substantiated` |
| M2 hedge stripping | "may be associated with" → "causes" | `partially_substantiated` or `not_substantiated` |
| M3 causal upgrade | correlational finding → causal mechanism | `not_substantiated` |
| M4 numeric drift | perturb the value; swap the denominator | `contradicted` |
| M5 temporal / scope drift | change year or setting | `not_substantiated` |
| M6 chain citation | retarget to the source's own cited source | `not_substantiated` |

`scripts/seed_miscitations.py` proposes mutations with the strong model; **a human accepts or
rejects each one** (this is the manual gate, and it is fast — accept/reject on a one-line diff).
One verified positive yields up to 6 hard negatives, so ~60 verified positives + ~40 natural
pairs comfortably reaches 250.

**Report seeded and natural negatives separately, always.** Seeded negatives are synthetic and
their difficulty distribution is not the real one. The **false-accusation rate must be computed
on natural pairs only** — measuring it against synthetic corruptions would flatter the system
in precisely the dimension §10 calls critical. Target ≥40 natural pairs including ≥15 natural
negatives; hand-auditing real runs is the only source for those.

### 7.4 Annotation tooling — extend the existing app

Options considered: standalone Streamlit; CLI with `$EDITOR`; extend `apps/web`.

**Recommendation: extend `apps/web` with a `/benchmark` route.** The expensive parts already
exist — `ClaimDetailDrawer.tsx` renders claim + retrieved chunks + evidence; `PaperView.tsx`
does PDF highlighting; the API already serves claim detail. What is missing is ~200 lines: a
five-way label widget, keyboard shortcuts (`1`–`5` for the verdicts, `h` for hard, `←/→` to
move), a span-selection handler that records `char_start`/`char_end` from a text selection, and
`POST /api/benchmark/{set}/label`.

Annotation speed **is** the project: 250 pairs at 3 min each is 12.5 h; at 90 s each it is
6 h. Tooling that halves per-item time pays for itself in the first sitting. The coupling cost
is acceptable and reversible — the route can be deleted when the set is frozen.

**Double annotation and adjudication are not optional.** Overlap ≥20% of pairs between two
annotators, report **Cohen's κ**, adjudicate disagreements, and record the adjudicator. Without
κ the gold set's own error rate is unknown — which is exactly the criticism the memo levels at
SciFact. A benchmark published without an agreement statistic is an opinion with a confusion
matrix attached.

### 7.5 Eval harness — `scripts/eval_gold.py`

Runs the **validator only** against frozen source text —
`LLMVerifier.verify_claim_against_source(claim, frozen_text)` — deliberately bypassing
acquisition. This isolation is essential: with a 31% download rate, an end-to-end evaluation
measures acquisition and reports it as judgment quality.

Outputs to `benchmarks/results/{timestamp}/`:

| Metric | Definition |
|---|---|
| Confusion matrix | 5×5 over the verdict ontology |
| **False-accusation rate** | of predictions in `ACCUSATION_VERDICTS`, the fraction whose gold label is `substantiated` or `partially_substantiated`. **Natural pairs only.** §8's target: <5%, published |
| Precision / recall | per verdict class |
| Abstention correctness | of predicted `not_checkable`, the fraction genuinely uncheckable |
| Recall on seeded errors | per M1–M7 type |
| Calibration curve + ECE | reliability diagram over `confidence`, defined only on non-abstentions (which is why `confidence` stays on checkable verdicts) |
| Determinism | N=3 repeats; verdict agreement rate (§8 target >95%) |
| Inter-annotator κ | on the double-annotated subset |

"Published", per the memo, means: committed in-repo as `benchmarks/results/latest/report.md`,
linked from the README, and **regenerated on every change to the judgment layer**. The report
must include the gold set's own κ and its natural/seeded composition, so a reader can discount
the numbers appropriately.

### 7.6 Sequencing note

0.4 cannot produce final numbers until P2–P5 are frozen, but **seed collection, tooling and
labelling all start at P1** and run concurrently. Labelling a claim–source pair does not depend
on how ASV judges it. Starting late is the single most likely way for Tier 0 to slip.

---

## 8. Source-code rewrites: the complete list, with justification

Every change that is more than an addition. Anything not listed here is additive.

| # | File | Change | Why a rewrite is unavoidable |
|---|---|---|---|
| R1 | `core/models.py:68-81` `ValidationResult` | `confidence` → Optional; `passed` → computed; add 6 fields + 2 validators | The contract *is* the defect. §0's diagnosis is a data-shape problem: the model can currently represent "confident verdict, no evidence." Additive-only changes leave that state representable, so the invariant in §5.1 would be advisory. This is the whole of 0.2 and 0.5 |
| R2 | `core/models.py:92-102` `ValidationBatch` | add `content_quality`, `judgeable`, `reference_check` | `download_successful` is a single boolean spanning two questions ("did bytes arrive" / "are they evidence"). 0.3 is precisely the act of separating them |
| R3 | `core/models.py:84-89` `ResolutionAttempt` | add `content_quality` | Makes the manifest the calibration corpus for §4.5 instead of a dead-end log |
| R4 | `orchestrator/claim_orchestrator.py:314-345` | rewrite `_process_uncited_qualitative` | 0.1. The method's entire body is the plausibility verdict |
| R5 | `orchestrator/claim_orchestrator.py:365-395` | delete branch A of `_process_uncited_quantitative` | 0.1, and it currently *gates acquisition on a plausibility score* — the worst instance of the pattern |
| R6 | `validator/llm_verifier.py:25-81` | delete `verify_claim` + `_build_verification_prompt` | 0.1. Deleting the callers but keeping the primitive guarantees it comes back |
| R7 | `validator/truth_table_checker.py` (whole file) + `validator/__init__.py` + `orchestrator/claim_orchestrator.py:74` | delete | Zero remaining call sites after R4/R5; holds an API key; makes network calls; writes `"No API key configured"` into 233 user-facing strings; already slated for Tier 4 |
| R8 | `orchestrator/process_qualitative.py:18-73` | delete the plausibility fallback; make `source_text` required; emit the new ontology; carry `EvidenceSpan`s | 0.1 + 0.2 + 0.5. Making the parameter required is what prevents the dead branch from silently resurrecting |
| R9 | `validator/llm_verifier.py:86-140` `verify_claim_against_source` | return a verdict rather than a bool; add quote verification; return `NOT_CHECKABLE(retrieval_empty)` instead of `passed=False` at `:99-106` | 0.2 + 0.5. `:99-106` is the line that reported 12 retrieval failures as failed claims |
| R10 | `validator/llm_verifier.py:203-233` prompt | new response schema + verbatim-quote instruction + `prompt_version` | 0.5. The model cannot return a verdict it was never asked for |
| R11 | `sourcefinder/text_downloader.py:75-149` `_process_bytes` | run the content assessment; return `content_quality`/`judgeable`; keep the 200-char floor as `REJECTED` only | 0.3. The single choke point both fetch paths share |
| R12 | `sourcefinder/text_downloader.py:327-464` `download_with_resolution` | first-success-wins → **best-of-N with early exit on `full_text`**; per-candidate filenames; delete non-winners | 0.3 is strictly harmful without it — see §4.4. This is the change most likely to introduce a regression; it needs the dedicated tests in §10 |
| R13 | `sourcefinder/text_downloader.py:187-239` `_extract_pdf_text` | also return page count | Needed by the classifier; currently discarded |
| R14 | `sourcefinder/academic_paper_finder.py:186-218` parse prompt | also return `type`, `volume`, `first_page`, `last_page` | 0.6 §6.6. Unlocks exact `ecitmatch` matching and `UNINDEXED_BY_DESIGN` routing at ~0 extra cost on an already-cached call |
| R15 | `orchestrator/claim_orchestrator.py:876-940` `_save_run_summary` | `_result_stats` must not average `None` confidences; add verdict counts and `reference_audit` | `sum(confidences)/len(confidences)` at `:895` raises `TypeError` the moment `confidence` can be `None`. Hard blocker, must land in P1 |
| R16 | `apps/api/services/read_model.py:64-70` `_derive_verdict` | pass through the persisted verdict; keep derivation as the **legacy** path for pre-change run folders | The 8 existing run folders are the evidence base for the memo's published numbers (Appendix A). Rewriting or deleting them destroys reproducibility; branching on a `_schema` version preserves it |
| R17 | `apps/api/schemas.py:22, 44-50, 100-107` | `Verdict` literal → 5 values; `ResultRef.confidence` → Optional; add evidence/reason/quality/flags; extend `VerdictBreakdown` | The API is a read model of the pipeline's types; it must track them |
| R18 | `apps/api/services/run_registry.py:88-114` | `_count_unresolved_and_totals` reads `passed` from raw JSON; recompute over verdicts; `pass_rate` → `substantiation_rate` over **checkable** claims only | Today `pass_rate = passed/(passed+failed)` silently counts 217 unsourced passes in the numerator. Leaving it is the headline metric continuing to lie after the verdict layer stops |
| R19 | `apps/web/src/lib/verdict.ts` + `VerdictBadge` + `VerdictBreakdownChart` + `ClaimDetailDrawer:25` + `ConfidenceGauge` | 5 verdicts + reason chips; render `—` for null confidence; evidence pane | `Record<Verdict, string>` is exhaustive — adding enum values is a type error until these are updated, which is the desired behaviour |

**Not rewritten, deliberately:** `AcademicPaperFinder.find_urls` cascade structure (Tier 1.1),
TF-IDF retrieval (Tier 2.1), `PythonScriptValidator` (Tier 4), `DatasetFinder` (Tier 4),
`BrowserSearcher` (Tier 1.5), citation attribution in extraction (Tier 1.7). Each is a real
defect; none is Tier 0; mixing them in makes the Tier 0 diff unreviewable.

---

## 9. Backward compatibility and migration

**Do not migrate the existing run folders.** They are the evidence base for every number in
`VALUE_PROPOSITION.md` and `SOURCE_ACQUISITION.md`, and Appendix A's reproduction snippets read
them directly. Rewriting them would destroy the ability to reproduce the memo's claims — which
is exactly the property the project says it values.

Instead:

1. Write `"_schema": 2` into every `validation_results/*.json` and manifest from P1 onward.
2. `read_model.py` branches: `_schema >= 2` → read the persisted `verdict`;
   absent → today's `_derive_verdict` mapped onto the new enum
   (`passed→substantiated`, `failed→not_substantiated`, `unresolved_source→not_checkable(source_download_failed)`,
   `skipped→not_checkable(validation_error)`), with `evidence=[]` and `confidence` passed
   through unchanged and clearly marked `legacy: true`.
3. The UI shows a "legacy run — pre-Tier-0 verdicts" badge on `_schema < 2` runs. A user
   comparing an old run to a new one in `ComparePage` must not read the change as a regression
   in the paper.
4. `revalidate_citation` (`claim_orchestrator.py:961`) writes v2 into a v1 file via
   `_merge_retry_into_results` (`:1014`). Handle explicitly: on a retry into a legacy file,
   upgrade the whole file to v2 (mapping the rest through the legacy mapper) so a single file
   never contains both shapes. This is a real edge case and it will bite in testing.

---

## 10. Tests

The memo notes (Tier 3.5) that **the orchestrator, validator and sourcefinder have no
dedicated test modules** — the three components that produce every user-visible verdict. Tier 0
cannot land safely on that base. Add `src/asv/validator/tests/`, `src/asv/sourcefinder/tests/`,
`src/asv/orchestrator/tests/` and extend `pytest.ini:testpaths`.

Minimum set, by PR:

| PR | Test | Asserts |
|---|---|---|
| P1 | `test_verdicts.py` | `substantiated` + empty evidence → `ValidationError`; `not_checkable` + confidence → `ValidationError`; reason code on a non-abstention → `ValidationError`; `passed` derives conservatively; `ValidationResult(**legacy_json)` does not raise |
| P1 | `test_run_summary_none_confidence.py` | `_result_stats` handles all-`None` confidences (guards R15) |
| P2 | `test_uncited_paths.py` | uncited qual/quant produce `not_checkable(no_source_available)`; `is_original` → `original_contribution`; **no LLM call is made** (assert on a mock client) |
| P3 | `test_quote_verification.py` | verbatim hit; whitespace/ligature/smart-quote variants hit; fabricated quote misses → `evidence_unverifiable`; empty retrieval → `retrieval_empty`, never `not_substantiated` |
| P4 | `test_content_quality.py` | fixtures: Nature landing page → `abstract_only`; Europe PMC full text → `full_text`; Springer subscription preview → `paywall_interstitial`; 1-page abstract PDF → `abstract_only`; 150-char error page → `rejected`. Fixtures trimmed, with provenance noted |
| P4 | `test_resolution_best_of_n.py` | abstract-first-then-full-text → full text wins; all-abstract → `abstract_only` with `judgeable=False`; early exit fires on the first `full_text` (assert call count); non-winning candidate files are deleted |
| P5 | `test_reference_verifier.py` | exact DOI hit → `verified`; title match with year off by one → `verified`; *Harrison's* chapter → `unindexed_by_design`; all APIs 5xx → `unverified`, **never** `not_found`; one index responding → `unverified`; near-miss recorded on rejection. All against recorded fixtures, no live network |
| P6 | `test_read_model_schema_versions.py` | a v1 run folder loads without error and is flagged legacy; a v2 folder passes verdicts through |

Mark network-touching tests `@pytest.mark.requires_api` (the marker already exists in
`pytest.ini`) and keep the default suite fully offline with recorded fixtures.

---

## 11. Projected impact on the measured run

`runs/hsv_cancer__20260706_192057`, 306 claims, 51 batches. Exact current counts are in
Appendix C.

| Bucket | Today | After Tier 0 | Driver |
|---|---:|---|---|
| Uncited, "passed" with `sources_used: []` | **217** | 0 | 0.1 — structurally impossible |
| `not_checkable(no_source_available / original_contribution)` | 0 | **~247** | 0.1 |
| `not_checkable(source_download_failed / not_resolved)` | reported as failed | **~35–39** | 0.2 (already a correction in P1) |
| `not_checkable(abstract_only / paywall_interstitial)` | silently judged | **~10** | 0.3 |
| `not_checkable(retrieval_empty)` | reported as failed claims (12) | **~12** | 0.5 |
| `not_checkable(reference_not_found)` | invisible | **unknown until measured** | 0.6 |
| Evidence-backed verdicts | 10 claimed, 0 with verified quotes | **≤10, every one with a verified quote and a URL** | 0.5 |
| Headline `pass_rate` | 73% | **~2–3% substantiation rate over checkable claims** | R18 |
| LLM calls per run | 306 judgment calls + parses | **~60** (247 plausibility calls deleted; ~10 abstract-only batches skip RAG) | 0.1 + 0.3 |
| New HTTP calls per run | 0 | **~700** (keyless, cached, rate-limited) | 0.6 |

Note the overlap: several of the 12 `retrieval_empty` claims are against the same Nature
landing pages that 0.3 reclassifies, so the buckets are not additive. The point stands
regardless — **Tier 0 does not change how many claims ASV can actually check (≈10); it changes
how many it *claims* to have checked (224 → ≈10).**

Cost and latency both improve: fewer LLM calls, and the ~700 new HTTP calls are cheap, cached
and parallelizable within polite limits.

---

## 12. Risks specific to this plan

| Risk | Severity | Mitigation |
|---|---|---|
| **0.6 falsely reports a real reference as not found** | **Critical** — an allegation of fabrication | Two-index quorum; `UNINDEXED_BY_DESIGN` routing; never the word "fabricated"; always show the near miss; hand-labelled precision on 253 references with a zero-false-positive bar before the status is shown in the UI |
| **0.3 thresholds mis-tuned, discarding real full text** | High — silently lowers the checkable rate, the metric Tier 1 is judged on | Calibrate against hand labels (§4.5); assert zero unsafe-direction errors in CI; log `content_signals` on every fetch so mis-tunings are diagnosable after the fact |
| **R12 (best-of-N) regresses acquisition** | High | Dedicated tests; A/B the batch download rate on `hsv_cancer.pdf` before/after using the existing run-compare machinery |
| **P1's "no-op" is not actually a no-op** | Medium | Golden-file test: run the orchestrator against a fixture claims JSON with a mocked LLM, assert output equals a committed snapshot modulo new keys |
| **The team ships Tier 0 alone and the tool looks broken** | Medium–High (product, not code) | §0. Pair with Tier 1.1/1.2 or with the free-wedge framing before any external exposure |
| **0.4 labelling starts late and blocks the published metrics** | Medium | Start at P1. It is the long pole and it is the item with no engineering workaround |
| **Politeness/ToS on ~700 new requests per run** | Medium | `mailto` polite pools, per-host token bucket, persistent cache, contact UA. All six services explicitly support this use; none is being scraped |
| **Ontology churn after gold labelling begins** | Medium | Freeze `verdicts.py` at P1. Any later change invalidates labels already collected |

---

## 13. Definition of done

Tier 0 is complete when all of the following hold:

1. `grep -rn "plausib" src/` returns nothing outside comments and the deleted-code changelog.
2. `ValidationResult` cannot be constructed with an evidenced verdict and no verified span —
   asserted by a test.
3. No `validation_results/*.json` produced after P5 contains a `substantiated`,
   `partially_substantiated`, `not_substantiated` or `contradicted` verdict without a
   `verified_verbatim` evidence span and a resolvable `source_url`.
4. Every fetch in `text_sources/_manifest.json` carries a `content_quality`, and no claim is
   judged against `abstract_only` content.
5. `runs/*/sourcefinder/reference_checks.json` exists for every new run and covers **every**
   reference in the bibliography, not just the cited-with-claims subset.
6. `benchmarks/results/latest/report.md` exists, is linked from the README, and reports
   precision, recall, **false-accusation rate on natural pairs**, abstention correctness, ECE,
   determinism, and the gold set's own inter-annotator κ.
7. The API serves, and the UI renders, all five verdicts plus reason codes, with evidence spans
   and source URLs on every judgment, and a legacy badge on pre-Tier-0 runs.
8. `pytest` passes with the three new test packages in `testpaths`, fully offline.
9. `CLAUDE.md`, `docs/README.md`, `docs/QUICKSTART.md` and `src/asv/validator/README.md` no
   longer document the plausibility path or `TruthTableChecker`.

---

---

## 14. Implementation record

Written after the fact, on 2026-09-15. The plan above is unedited; this section
records what landed, what deviates from it, and — importantly — what is built
but **not yet validated against reality**.

### 14.1 What landed

| Item | Status | Where |
|---|---|---|
| 0.2 verdict ontology | done | `src/asv/core/verdicts.py`, `core/models.py` |
| 0.1 delete plausibility | done | `claim_orchestrator.py`, `process_qualitative.py`, `llm_verifier.py`; `truth_table_checker.py` deleted |
| 0.5 evidence invariant + quote verification | done | `models.py` validator, `llm_verifier.py` |
| 0.3 content-quality gate + best-of-N resolution | done | `sourcefinder/content_quality.py`, `text_downloader.py` |
| 0.6 reference existence + retraction | done | `sourcefinder/reference_verifier.py`, `index_clients.py` |
| API + frontend | done | `apps/api/`, `apps/web/` incl. new References and Benchmark screens |
| 0.4 gold set | **tooling only** | `src/asv/benchmark/`, four scripts, `/benchmark` UI — **zero pairs labelled** |
| Tests | done | 269 passing; three new test packages; 70% coverage, up from 38% |

The P1-as-a-no-op sequencing in §1 was not followed: the ontology and its
consumers landed together, because the invariant in 0.5 makes several of the
intermediate states unconstructible, so a genuinely behaviour-preserving P1 would
have had to introduce and then immediately remove a set of compatibility shims.
The mapping table in §2.4 was still used, as the specification of what each site
had to emit.

### 14.2 Deviations from the plan, and why

1. **Shared enums live in `core/verdicts.py`**, not in `sourcefinder/content_quality.py`
   and `sourcefinder/reference_verifier.py` as §2.2 and Appendix A said. `core/models.py`
   references `ContentQuality`, `ReferenceStatus` and `RetractionStatus`, and `core`
   must not import from `sourcefinder` — every other package depends on `core`, never
   the reverse. The sourcefinder modules re-export them, so the import paths the plan
   names still resolve.

2. **Schema versioning is a sidecar plus per-entry detection**, not a wrapper object
   (§9.1). Wrapping `validation_results/*.json` in `{"_schema": 2, "results": [...]}`
   would break the plain-list shape that every analysis snippet in
   `VALUE_PROPOSITION.md` Appendix A depends on — including the ones that produced
   the project's published numbers. Instead: `validation_results/_schema.json` records
   the version for the run, and `read_model` treats any *entry* lacking a `verdict`
   key as legacy. That also handles the mixed-shape file §9.4 worried about, with no
   special case.

3. **Legacy plausibility rows render as abstentions, not as `substantiated`.**
   §9.2 proposed mapping a legacy `passed: true` to `substantiated` behind a badge.
   That would reproduce, in the new UI, exactly the claim Tier 0 exists to stop
   making — 217 of the reference run's 224 passes came from the plausibility path
   with `sources_used: []`. They now read as `not_checkable(no_source_available)`
   with `legacy: true`, and the original boolean is preserved in
   `validation_metadata.legacy_passed`. The run files themselves are untouched, so
   Appendix A still reproduces.

4. **`_count_unresolved_and_totals` was replaced rather than rewritten** (R18). It
   existed to let the listing view skip loading `claims.json`; keeping it would have
   meant duplicating the legacy-mapping logic in a second place, where it could
   silently disagree with the detail view about the same run. It now calls
   `build_claim_rows`, which is cached on file mtime.

5. **Journal-abbreviation matching does subsequence matching, not just prefix**
   (beyond §6.5). `J Virol` → `Journal of Virology` works on prefixes, but `Natl` →
   `National` does not, and this corpus's references are uniformly abbreviated.
   Gated on a shared first letter and a three-character minimum to keep it tight.

6. **A pipeline smoke test was added** (`test_pipeline_smoke.py`), which §10 did not
   call for. Five separate rewrites touching the same call path needed one test that
   runs all of them together; it caught the `claims.json` coupling in the read model
   that no unit test would have.

### 14.3 Built but NOT yet validated — read this before trusting any of it

- **The P0 spike was never run.** `scripts/probe_existence_apis.py` exists and is
  correct as far as static review goes, but it requires network and has not been
  executed. **The field paths in `index_clients.py` are therefore unverified against
  the live APIs.** §6.8 was explicit that the matcher should not be coded against
  remembered field names; it was anyway, because the alternative was not shipping
  0.6 at all. Run the probe before trusting a single reference-audit result, and
  treat a run of all-`unverified` statuses as an extraction-path bug rather than as
  evidence about the bibliography.
- **The content-quality thresholds are uncalibrated.** They are the plan's starting
  points. `scripts/calibrate_content_quality.py` is written but has not been run, and
  no URL has been hand-labelled. The unit tests pin the *decision boundaries the
  classifier is supposed to have* on synthetic fixtures; they do not establish that
  those boundaries are right for real publisher HTML.
- **The gold set is empty.** All of §7's tooling exists — schema, seeder, mutation
  generator, annotation UI with keyboard shortcuts, evaluation harness, and every
  metric in VALUE_PROPOSITION.md §8 including the natural-pairs-only false-accusation
  rate. Zero pairs are labelled, so **there is still no defensible quality claim
  about ASV.** This remains the long pole, exactly as §1 predicted, and it is the
  one part no amount of engineering removes.
- **No full pipeline run against a real PDF** has been made since the change. The
  smoke test stubs the LLM and the network.

### 14.4 The honest headline

Re-reading `runs/hsv_cancer__20260706_192057` through the new read model, that run
now reports:

| | before | after |
|---|---:|---:|
| substantiated | 224 "passed" | **7** |
| not substantiated | — | 15 |
| not checkable | 0 | **284** |
| checkable rate | not measured | **7.2%** |
| evidence-backed verdicts | not recorded | **0** (legacy runs predate evidence capture) |

The 7 and the 15 match the funnel in VALUE_PROPOSITION.md §2.2 exactly (7 positive
and 3 negative substantive judgments, plus the 12 retrieval failures that were being
reported as failed claims). Nothing was lost in the rewrite; the reporting stopped
hiding it.

§0 of this plan predicted this and it holds: **Tier 0 did not change how many claims
ASV can check. It changed how many it claims to have checked.** Tier 1 —
source acquisition — is the only thing that moves the first number.

## Appendix A — File-by-file change inventory

**New files**

```
src/asv/core/verdicts.py                         Verdict, NotCheckableReason, verdict sets
src/asv/sourcefinder/content_quality.py          ContentQuality, ContentAssessment, classifier
src/asv/sourcefinder/reference_verifier.py       ReferenceVerifier, ReferenceCheck, matchers
src/asv/sourcefinder/index_clients.py            Crossref / OpenAlex / EuropePMC / PubMed / DataCite
src/asv/validator/tests/                         new test package
src/asv/sourcefinder/tests/                      new test package
src/asv/orchestrator/tests/                      new test package
scripts/probe_existence_apis.py                  P0 spike
scripts/calibrate_content_quality.py             P0 calibration
scripts/build_gold_seed.py                       0.4
scripts/seed_miscitations.py                     0.4 hard negatives
scripts/eval_gold.py                             0.4 eval harness
benchmarks/gold/*.jsonl, benchmarks/sources/     0.4 data
apps/api/routers/benchmark.py                    0.4 annotation endpoints
apps/web/src/routes/BenchmarkAnnotator.tsx       0.4 annotation UI
```

**Modified** — see §8 R1–R19 for the justification of each.

```
src/asv/core/models.py                   R1 R2 R3
src/asv/core/run_paths.py                + reference_checks_json()
src/asv/core/llm_config.py               + prompt_version on source_grounded_verification
src/asv/orchestrator/claim_orchestrator.py   R4 R5 R7 R15 + stage 0.5 + 3-way batch branch
src/asv/orchestrator/process_qualitative.py  R8
src/asv/orchestrator/process_quantitative.py + verdict mapping
src/asv/validator/llm_verifier.py        R6 R9 R10
src/asv/validator/truth_table_checker.py R7 (delete)
src/asv/validator/__init__.py            R7
src/asv/sourcefinder/text_downloader.py  R11 R12 R13
src/asv/sourcefinder/academic_paper_finder.py R14 + accept a pre-resolved DOI
src/asv/sourcefinder/source_manifest.py  + content_quality passthrough
apps/api/schemas.py                      R17
apps/api/services/read_model.py          R16
apps/api/services/run_registry.py        R18
apps/api/routers/claims.py               + reason-code facet
apps/web/src/lib/verdict.ts, VerdictBadge.tsx, VerdictBreakdownChart.tsx,
  ClaimDetailDrawer.tsx, ConfidenceGauge.tsx, ClaimsExplorer.tsx, ComparePage.tsx   R19
apps/web/src/api/types.ts                regenerate: npm run gen-types
pytest.ini                               + 3 testpaths
CLAUDE.md, docs/README.md, docs/QUICKSTART.md, src/asv/validator/README.md,
  src/asv/orchestrator/README.md         P8
```

**Dependencies:** none added. `rapidfuzz==3.11.0` is already declared in `pyproject.toml:39`
and currently imported nowhere — it covers both the reference matcher (§6.5) and quote
verification (§5.4).

---

## Appendix B — Contracts to confirm in the P0 spike

Do not code §6 against remembered field names. For each service, record: base URL, the exact
parameter names, auth/politeness requirements, rate limits and their headers, and the JSON path
to title, authors, year, DOI, and retraction status.

| Service | What to confirm |
|---|---|
| Crossref | `query.bibliographic` behaviour and `select`; `mailto` polite-pool header; `message.items[].{title,author,issued,DOI,container-title}`; `update-to[]` shape for retractions |
| OpenAlex | `filter=doi:` vs `filter=title.search:` vs `search=`; `mailto`; `is_retracted`; `per_page` limits |
| Europe PMC | `search` query syntax and `resultType`; how retraction / expression-of-concern is expressed |
| PubMed | `esearch` vs `ecitmatch` input format (`journal|year|volume|firstpage|author|key`); whether a key is needed at our volume; `Retracted Publication` publication type |
| DataCite | `/dois?query=` response shape |
| Retraction Watch via Crossref | current distribution endpoint and licence terms |

Deliverable: a short markdown table committed to `docs/`, referenced from
`reference_verifier.py`.

---

## Appendix C — How the numbers in this plan were computed

Run from the repo root.

```python
import json, io, collections
from urllib.parse import urlparse
B = 'runs/hsv_cancer__20260706_192057/'
L = lambda p: json.load(io.open(B + p, encoding='utf-8'))

# §3.1 / §11 — the plausibility path
u = (L('validation_results/qualitative_uncited_results.json')
   + L('validation_results/quantitative_uncited_results.json'))
print(len(u), collections.Counter(r['validation_method'] for r in u))
#  -> 247  {'truth_table+llm_check': 233, 'truth_table+llm_only': 10, 'source_not_found': 4}
print(sum(r['passed'] for r in u), sum(1 for r in u if not r['sources_used']))   # -> 217 247

# §4.1 — what the successful downloads actually were
for f in ('qualitative_cited_results.json', 'quantitative_cited_results.json'):
    bs = L('validation_results/' + f)
    print(f, len(bs), sum(1 for b in bs if b['download_successful']))
    print(collections.Counter(urlparse(b['source_url']).netloc
                              for b in bs if b.get('source_url')).most_common())
    print('no-relevant-chunks:', sum(1 for b in bs if b['download_successful']
                                     for cr in b['claim_results']
                                     if 'No relevant chunks' in (cr['explanation'] or '')))
#  qual: 37 batches, 12 downloaded, nature.com x6, europepmc x2, ... , 9 no-chunk
#  quant: 14 batches,  4 downloaded, nature.com x3, europepmc x1,      3 no-chunk

# §6.2 — the bibliography this has to work on
import re
c = L('citations/hsv_cancer_claims.json')['citations']
print(len(c), sum(1 for v in c.values() if re.search(r'10\.\d{4,}/', v)))        # -> 253, 0
print([k for k, v in c.items()
       if re.search(r'\bIn:|\(eds?\)|McGraw-Hill|Springer-Verlag', v, re.I)])    # -> ['1', '16']
years = [int(re.findall(r'(19\d{2}|20\d{2})', v)[-1]) for v in c.values()
         if re.findall(r'(19\d{2}|20\d{2})', v)]
print(len(years), min(years), max(years), sum(1 for y in years if y < 1970))     # -> 245 1904 2068 1
```

Dependency and line-anchor claims (`rapidfuzz` unused, `TruthTableChecker` call sites,
`sources_used` polysemy) were verified with:

```bash
grep -rn "rapidfuzz" src apps scripts --include=*.py
grep -rn "truth_table\|TruthTable\|sources_used" src apps scripts docs --include=*.py --include=*.md --include=*.tsx
```
