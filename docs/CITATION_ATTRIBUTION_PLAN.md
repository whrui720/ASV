# Citation Attribution (VP Tier 1.7) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every claim carries every reference its sentence cites, plus an honest record of
how that attribution was made. ASV never accuses a claim on the strength of a citation it
guessed, or of only part of the citation set.

**Architecture:** Citation markers become typographic facts read from the PDF (PyMuPDF
superscript flags, plus `[n]` in the text) and are no longer something the LLM reports.
Claims are located in the text with a letters-only aligner, and markers are assigned by
position: own sentence first, then the nearest marker in the same paragraph, recorded as
*inherited*. The orchestrator judges a claim against each cited source and aggregates with
one rule. Positive verdicts need one supporting source. Negative verdicts need the whole
cited set judged, and are never issued on an inherited attribution.

**Tech Stack:** Python 3, PyMuPDF 1.25.1 (already pinned), pydantic v2, rapidfuzz, pytest, FastAPI, React/TS.

**Spec:** Part I of this document (root-cause findings, measured on run
`hsv_cancer__20260923_204743`), and `docs/VALUE_PROPOSITION.md` §2.5 and §7 row 1.7.

---

## Part I: Root causes (measured 2026-11-01)

**Method.** PyMuPDF flags superscript spans in the source PDF. In this paper they are the
citation markers: 334 spans at 6.9 pt against 9.7 pt body text, forming 177 marker groups
in the body. That gives a ground truth that doesn't depend on the LLM. All 310 extracted
claims were aligned against it with casefolded letters-only matching; 303 aligned. This was a
one-off analysis; Task 10's audit script makes the routine version of it permanent.

| Claim group (as the run labelled it) | Claims | Ground truth |
|---|---:|---|
| LLM found a marker, mapper resolved it | 58 | 55 have a marker in their own sentence |
| **LLM found a marker, mapper dropped it** | **65** | **all 65 have a marker in their own sentence** |
| LLM reported no marker | 163 | 10 own-sentence (LLM miss) · **98 cited by a later sentence in the paragraph** · 17 by an earlier one · 34 paragraph uncited · 4 unaligned |
| LLM said "original contribution" | 24 | All are background statements in a *review*; 17 sit in cited paragraphs |

The LLM's markers are accurate: of 122 checkable, 109 match the ground truth exactly, 11
overlap and 0 are disjoint. It detects 120 of 130 own-sentence markers (92%).

**RC1: the marker→reference mapper parses one number.** `_extract_citation_id`
(`claim_extractor.py:401`) handles `[12]` and `12` only. Lists (`49,50`), ranges
(`24–27`), mixed forms (`52,61,53,62–64,60`), bracketed lists (`[81, 82]`) and
`Pollara et al.58` fall through to a string that isn't a key, and the claim is silently
recorded as uncited. That loses **65 of 123 (53%)** detected markers. 72 of the body's 177
marker groups cite more than one reference (up to 8).

**RC2: no citation scope.** A claim counts as cited only if its own sentence carries a
marker. Fewer than half of this review's body sentences carry a marker. A citation at the
end of a passage covers the sentences before it, and sometimes the ones after. 115 claims
have a marker in their paragraph but not their sentence. For 101 of the 110 with a
*following* marker, it is 1–3 sentences away (53 / 29 / 19).

**RC3: the reference parser splits and pollutes entries.**
- (a) The entry splitter `\n(?=\d+\.?\s+[A-Z])` (`utils.py:126`) requires an uppercase
  letter after the number. So `81 al-Rikabi` and `91 van Dillen` merged into entries 80 and
  90, and keys 81 and 91 don't exist.
- (b) Page furniture became references. Footer page numbers 986–992 produced 7 junk keys
  (`"992": "Cancer Gene Therapy"`), and the running title is appended to entry 247.
- Seven of the Stage 0 audit's 13 "unverified" references are these junk keys.

**RC4: marker detection runs on text that destroys markers.** PyPDF flattens superscripts
into digits glued to words (`stomatitis.1 Chronic`), which `ICP34.5` makes ambiguous. The
superscript en-dash in this PDF's font is an unmappable glyph, so it arrives as U+FFFD
(`3�5`). Whether a superscript is present is a typographic fact the PDF already records,
so asking an LLM to infer it is the wrong design.

**RC5: `is_original` is an unchecked LLM judgment.** 24 claims in a review article were
routed to `not_checkable(original_contribution)`, for example "The most frequently used
suicide gene is the native HSV-1 thymidine kinase gene". The label also blocks RC2's fix.

**RC6 (prerequisite): claim location fails on 88 of 310 claims (28%).**
`_locate_claim_span` tries an exact match and then a whitespace-tolerant one. It fails on:
- line-end hyphenation (`trans-\nmitted`)
- glued superscript digits
- the LLM repairing missing sentence spaces (`diseases.Herpes`)

A letters-only alignment locates 303 of 310 (98%). Assigning markers by position depends on
locating the claim, so this fix comes first.

**Corrections to VP §2.5.**
- "Nearly every sentence carries a reference" is false; fewer than half do.
- "The extraction prompt shows only the first 10 references" is true but not the cause. Marker
  detection doesn't use the reference list, and recall is already 92% without it. The fix is
  to **remove** the list, not to send all 247 references with every chunk (~12k extra tokens
  per call).
- "Chunk boundaries split them" stops mattering once markers are assigned by document
  position. Chunk overlap does produce 2 duplicate claim pairs; that's minor and out of scope.

**Downstream blockers.** Fixing RC1 alone would be unsafe:
- **D1.** A claim holds one `citation_id`. Checking only the first of `43,46,47` and
  reporting `not_substantiated` is a false accusation whenever 46 is the supporting source.
- **D2.** Each batch resolves its source from `first_claim.citation_details`
  (`claim_orchestrator.py:1106`). That object describes the claim's first reference, so a
  claim joining the batch for reference 46 would fetch reference 43's DOI.
- **D3.** The API read model indexes results by `claim_id` with last write winning
  (`read_model.py:193-232`), and the run summary flattens batches. A claim present in
  several batches would show an arbitrary result and be counted several times.

**Projected effect on this paper:**
- Attributed claims go from 58/310 (19%) to about 130 explicit (42%) plus about 130
  inherited (42%). About 48 (15%) stay uncited.
- Distinct references the orchestrator must acquire rise from 51 to as many as 243.
- **Expectation:** last run's full-text rate was 1 of 51. Until the Tier 1 credential work
  lands (`SOURCE_ACQUISITION.md` §11), most newly attributed claims will move from
  `no_source_available` into acquisition abstentions (`abstract_only`,
  `source_download_failed`), not into verdicts. Attribution is necessary but not sufficient.

**Non-goals:**
- Deterministic author-year markers. They need an author-year test paper, and today's LLM
  path is kept for them.
- LLM-judged citation scope.
- Footnote-style citations.
- Making `claim.text` a verbatim source slice.
- Deduplicating chunk-overlap claims.

## Global Constraints

- `ValidationResult`'s invariants are unchanged. Aggregated results are built through
  `ValidationResult(...)` / `not_checkable(...)` and never bypass the validator.
- An **inherited** attribution can yield only `substantiated`, `partially_substantiated` or
  `not_checkable(citation_inferred)`.
- `not_substantiated` or `contradicted` on a multi-cited claim requires **every** cited
  source to have been judged. Ids past `MAX_CITATIONS_PER_CLAIM = 8` are never fetched, so a
  claim citing more than 8 references can only come out positive or `not_checkable`.
- `location_in_text` offsets index `citations/{stem}_text.txt` exactly (the B2 contract;
  `apps/api/services/pdf_highlights.py` depends on it).
- `ClaimObject.citation_id` stays and equals the first cited id. Historical run folders must
  load and render unchanged.
- `core` imports nothing from `extraction`, `orchestrator` or `sourcefinder`.
- No new dependencies. Tests run offline. Tests that need `pdfs/hsv_cancer.pdf` (untracked)
  skip when it's absent.
- **Don't merge Tasks 1–6 without Tasks 7–8.** On their own they check multi-cited claims
  against the first reference only.
- The repo is on `main` with unrelated uncommitted work. Branch to `fix/citation-attribution`
  before the first commit.

## Review Focus

1. **Superscripts that aren't citations:** exponents (`10⁶`), units (`cm²`), primes that
   PyMuPDF renders as superscript `0` (`b′a′`). These must never become markers (Task 3 test).
2. **A paragraph continued across a column or page break, with its citation in the
   continuation.** Inheritance must still find it (Task 3 test).
3. **A paper with no superscript or bracket markers (author-year).** Each claim must fall
   back to the LLM marker exactly as today and lose no citation it has now (Task 5 test).
4. **Two sentences identical except for their numbers** ("survival was 20%" vs "40%"). The
   claim must locate to the right one, or it inherits the wrong citation (Task 4 test).
5. **Historical runs:** claims JSON without `attribution`, no `claim_verdicts.json`. These
   must load and render as before (Task 1 and Task 9 tests).

---

## Part II: Tasks

Phase 1 (Tasks 1–6) fixes extraction. Phase 2 (Tasks 7–9) makes verdicts safe over cited
sets. Phase 3 (Task 10) measures the result.

### Task 1: Resolve every reference a marker names

**Files:**
- Create: `src/asv/extraction/citation_markers.py`
- Modify: `src/asv/core/models.py` (`ClaimObject`), `src/asv/extraction/claim_extractor.py:176-200,400-415`
- Test: `src/asv/extraction/tests/test_citation_markers.py`; update the `_extract_citation_id` tests in `test_claim_extractor.py:487-510`

**Interfaces:**
- Produces:
  - `parse_marker(raw: str, known_ids: Collection[str], max_range: int = MAX_RANGE_SPAN) -> List[str]`, with `MAX_RANGE_SPAN = 50`.
  - `resolve_marker(raw: str, citations: Dict[str, str]) -> List[str]`: numeric via `parse_marker`; if that yields nothing, the legacy author-year surname lookup moved verbatim from `_extract_citation_id`.
  - In `core/models.py`:
    - `class AttributionKind(str, Enum): EXPLICIT="explicit"; INHERITED="inherited"; LLM_MARKER="llm_marker"; NONE="none"`
    - `class CitationAttribution(BaseModel): kind: AttributionKind; citation_ids: List[str] = []; marker_spans: List[Tuple[int, int]] = []; sentence_distance: int = 0`
    - `ClaimObject.attribution: Optional[CitationAttribution] = None`
    - `ClaimObject.citation_ids` is a plain `@property`: `attribution.citation_ids` if non-empty, else `[citation_id]` if set, else `[]`.

- [ ] **Step 1: Write the failing tests**

```python
KNOWN = {str(i) for i in range(1, 248)}

@pytest.mark.parametrize("raw, expected", [
    ("[12]", ["12"]),
    ("49,50", ["49", "50"]),
    ("24–27", ["24", "25", "26", "27"]),
    ("3�5", ["3", "4", "5"]),                     # unmappable en-dash glyph
    ("52,61,53,62�64,60", ["52", "61", "53", "62", "63", "64", "60"]),
    ("[81, 82]", ["81", "82"]),
    ("57 and Pollaraet al.58", ["57", "58"]),
    ("5–900", ["5"]),                              # span > 50: endpoints only, 900 unknown
    ("27–24", ["27", "24"]),                       # reversed: endpoints only
    ("12,12", ["12"]),
])
def test_parse_marker(raw, expected):
    assert parse_marker(raw, KNOWN) == expected

def test_parse_marker_drops_ids_not_in_bibliography():
    assert parse_marker("91", {"90"}) == []

def test_resolve_marker_keeps_author_year_lookup():
    assert resolve_marker("(Smith, 2020)", {"Smith": "Smith, J. (2020)."}) == ["Smith"]

def test_legacy_claim_json_loads_with_primary_as_only_citation():
    c = ClaimObject.model_validate({"claim_id": "c1", "text": "x", "claim_type": "qualitative",
                                    "citation_found": True, "citation_id": "7", "citation_text": "[7]"})
    assert c.attribution is None and c.citation_ids == ["7"]

def test_map_citations_records_every_cited_id():
    ex = HybridClaimExtractor.__new__(HybridClaimExtractor)          # no LLM client needed
    ex.citations = {str(i): f"ref {i}" for i in range(1, 61)}
    ex.claims = [ClaimObject(claim_id="c1", text="x", claim_type="qualitative",
                             citation_found=True, citation_text="49,50")]
    claim = ex.map_citations_to_claims()[0]
    assert claim.citation_ids == ["49", "50"] and claim.citation_id == "49"
    assert claim.attribution.kind == AttributionKind.LLM_MARKER
```

- [ ] **Step 2: Run them and confirm they fail.** `pytest src/asv/extraction/tests/test_citation_markers.py -v` should fail with an ImportError.
- [ ] **Step 3: Implement.**
  - The dash class is `[‐-―\-�]`.
  - Split parts on `,`, `;` and the word `and`. In each part, `(\d+)\s*<dash>\s*(\d+)` is a range when `a < b <= a + max_range`, and otherwise contributes its endpoints. A part with no range contributes all its `\d+`.
  - Dedupe, keeping order of appearance, then filter by `known_ids`.
  - `map_citations_to_claims` sets `attribution=CitationAttribution(kind=LLM_MARKER, citation_ids=ids)` and `citation_id=ids[0]`. Delete `_extract_citation_id`.
- [ ] **Step 4: Run the tests; they pass.** Also run `pytest src/asv/extraction -q`; it stays green.
- [ ] **Step 5: Commit:** `fix(extraction): resolve every reference a citation marker names`

### Task 2: Reference list: sequential entries, no page furniture

**Files:**
- Modify: `src/asv/extraction/utils.py:110-135` (numeric/vancouver branch of `parse_citations_deterministic`)
- Test: `src/asv/extraction/tests/test_utils.py`

**Interfaces:**
- Consumes nothing new; same signature.
- Produces: numbered entries keyed `"1".."N"` with no furniture keys.

- [ ] **Step 1: Write the failing tests**

```python
REFS = ("79 Forrester A, Lipsey JR. Construction of a mutant. J Virol 1992; 66: 341–348.\n"
        "80 Gupta N. Current status of viral gene therapy for brain tumours.\n"
        "Expert Opin Invest Drugs 2000; 9: 713–726.\n986\nCancer Gene Therapy\n"
        "81 al-Rikabi AC, al-Sohaibani MO. Metastatic deposits of a malignant glioma.\n"
        "Cancer Gene Therapy\n"
        "82 Hsu E, Keene D. Bone marrow metastasis in astrocytic gliomata.\n"
        "Cancer Gene Therapy\n73: 3210–3215.\n")

def test_lowercase_surname_starts_an_entry_and_furniture_is_dropped():
    c = parse_citations_deterministic(REFS, "numeric")
    assert list(c) == ["79", "80", "81", "82"]
    assert c["81"].startswith("al-Rikabi AC")
    assert "986" not in c["80"] and "Cancer Gene Therapy" not in c["80"]
    assert c["82"].endswith("73: 3210–3215.")          # a volume line is a continuation

def test_one_missing_entry_does_not_stop_the_split():
    c = parse_citations_deterministic("1 Able A. One.\n2 Baker B. Two.\n4 Dog D. Four.\n", "numeric")
    assert list(c) == ["1", "2", "4"]
```

- [ ] **Step 2: Run them; they fail.** Currently `"81"` is missing and `"986"` is a key.
- [ ] **Step 3: Implement.**
  - Before splitting, drop lines that are only digits, and drop whole lines (after strip) that occur at least 3 times in the section.
  - Walk the lines. A line matching `^(\d{1,4})\.?\s+\S` starts a new entry only when its number is `expected` or `expected + 1`, where `expected = previous + 1` and the first entry seeds `previous`. Any other line continues the current entry.
- [ ] **Step 4: Run the tests; they pass.** `pytest src/asv/extraction -q` stays green.
- [ ] **Step 5: Commit:** `fix(extraction): sequential reference splitting; drop page furniture`

### Task 3: Document text with citation markers from the PDF

**Files:**
- Create: `src/asv/extraction/pdf_text.py`; `src/asv/extraction/tests/pdf_fixtures.py` (PDF writer and `make_doc`)
- Test: `src/asv/extraction/tests/test_pdf_text.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class TextMarker: start: int; end: int; raw: str` (offsets into `text`).
  - `@dataclass class ExtractedDocument`, with:
    - `text: str`
    - `markers: List[TextMarker]`, in text order
    - `paragraphs: List[Tuple[int, int]]`
    - `def llm_view(self, end: Optional[int] = None) -> str`: `text[:end]` with each marker span replaced by `"[" + raw + "]"`
  - `extract_document(pdf_path: str) -> ExtractedDocument`
  - `find_bracket_markers(text: str) -> List[TextMarker]`
  - Test helpers:
    - `write_pdf(path, pages: List[List[Optional[List[Run]]]]) -> Path`, where `Run = (text, size, sup)`. It lays out runs left to right with `fitz.get_text_length`, raises `sup` runs by 0.35 × the line's first run size, puts lines 12 pt apart, and treats a `None` line as a paragraph gap.
    - `make_doc(marked: str) -> ExtractedDocument`. In the input, `^{…}` marks a superscript (kept in `text` without the braces and caret), `\n\n` separates paragraphs, and bracket markers come from `find_bracket_markers`.

- [ ] **Step 1: Write the failing tests:**
  - `test_superscript_digits_become_markers`: runs `("gingivo stomatitis.", 9.7, False), ("1", 6.9, True), (" Chronic infection.", 9.7, False)`. Expect `[m.raw for m in doc.markers] == ["1"]`, `doc.text[m.start:m.end] == "1"` and `"stomatitis.1 Chronic" in doc.text`.
  - `test_adjacent_superscript_spans_merge`: sup runs `"12"` then `"13"` produce one marker, and `parse_marker(raw, KNOWN) == ["12", "13"]`.
  - `test_exponents_units_and_primes_are_not_markers`: `"10"`+sup`"6"`, `" cells per cm"`+sup`"2"`, `" and b"`+sup`"0"`. Expect `doc.markers == []`.
  - `test_brackets_are_markers_but_enumerations_are_not`: `find_bracket_markers("channels [12]. (1) An electron-opaque core.")` gives raws `["12"]`.
  - `test_running_header_and_page_numbers_are_removed`: 3 pages, each with `"Cancer Gene Therapy"` at y=30 and `"975"`/`"976"`/`"977"` at the bottom. Neither string is in `doc.text`.
  - `test_paragraph_continued_across_pages_is_one_paragraph`: page 1 ends `"The capsid is composed of 162 capsomers arranged in"`; page 2 starts `"an icosahedral symmetry. It contains channels."`+sup`"2"`. One `(s, e)` in `doc.paragraphs` contains both `text.index("capsid")` and the marker's start.
  - `test_llm_view_brackets_markers`: `"stomatitis.[1] Chronic" in doc.llm_view()`.
- [ ] **Step 2: Run them; they fail with an ImportError.**
- [ ] **Step 3: Implement `extract_document`** with `page.get_text("dict")`, in stream order with no sort, skipping image blocks.
  - **Superscript:** `span["flags"] & 1`, or `size <= 0.8 ×` the line's largest span size with its origin y raised at least `0.15 ×` that size.
  - **Marker eligibility:** the superscript text matches `^\s*\d[\d\s,‐-―\-�]*$` and isn't `"0"`. The preceding text character isn't a digit. The preceding whitespace token isn't in `{"m","cm","mm","km","µm","nm"}`. Adjacent superscript spans merge, joined with `","`.
  - **Furniture:** a block inside the top or bottom 7% of page height that is all digits, or whose digit-stripped text recurs on 3 or more pages.
  - **Assembly:** spans concatenate, lines join with `"\n"`, blocks with `"\n\n"`. A block whose text (ignoring a trailing marker) doesn't end in `.`, `!`, `?` or `:` joins the next block with `"\n"`, so the paragraph continues.
  - Bracket markers come from `find_bracket_markers` (`\[(\d[\d\s,‐-―\-�]*)\]`) over the assembled text and are merged into `markers` by offset.
- [ ] **Step 4: Run the tests; they pass.**
- [ ] **Step 5: Commit:** `feat(extraction): PyMuPDF document text with citation-marker offsets`

### Task 4: Locate claims despite hyphenation, glued markers and respacing

**Files:**
- Create: `src/asv/extraction/claim_location.py`
- Test: `src/asv/extraction/tests/test_claim_location.py`

**Interfaces:**
- Produces: `class ClaimLocator: __init__(self, text: str)` and `locate(self, claim_text: str, hint: int = 0) -> Tuple[Optional[int], Optional[int]]`.

- [ ] **Step 1: Write the failing tests.** In each, `L = ClaimLocator(text)`.
  - Hyphenation: text `"is associated with sexually trans-\nmitted diseases. Herpes"`, claim `"is associated with sexually transmitted diseases."`. The span starts at index 0 and contains `"mitted diseases."`.
  - Glued marker: text `"Acute HSV-1 infection generally involves gingivo stomatitis.1 Chronic"`. The span equals `"Acute HSV-1 infection generally involves gingivo stomatitis."`, with the trailing `.!?` included.
  - Missing space: text `"diseases.Herpes simplex virus type 1 is also a human pathogen."`. Start is `text.index("Herpes")`.
  - Numbers disambiguate: text `"Survival was 20% in group A. Later, survival was 40% in group A."`, claim `"survival was 40% in group A."`. Start is `text.index("survival was 40%")`.
  - Hint picks the later of two identical sentences.
  - Edited first word: claim `"An acute HSV-1 infection generally involves gingivo stomatitis in most patients seen in clinics."` against text starting `"Acute HSV-1 infection generally involves …"` returns a span containing `"infection generally involves"`.
  - Too short (`"HSV-1."`) and paraphrase return `(None, None)`.
- [ ] **Step 2: Run them; they fail.**
- [ ] **Step 3: Implement.**
  - Try an exact match first, preferring at or after `hint` (today's behaviour).
  - Otherwise use a casefolded letters-only string with an index map back to `text`, built once in `__init__`. Try occurrences at or after `hint`, then from 0.
  - Accept an occurrence only if the claim's digit runs appear, in order, inside the mapped span.
  - Under 15 letters returns `(None, None)`.
  - If there's no full match and the claim has at least 60 letters, retry with the first and last 10 letters dropped; the span then covers the core.
- [ ] **Step 4: Run the tests; they pass.**
- [ ] **Step 5: Commit:** `feat(extraction): letters-only claim locator with digit check`

### Task 5: Attribute claims by position; gate `is_original`

**Files:**
- Create: `src/asv/extraction/attribution.py`
- Test: `src/asv/extraction/tests/test_attribution.py`

**Interfaces:**
- Consumes: `ExtractedDocument`, `TextMarker`, `make_doc` (Task 3); `parse_marker`, `resolve_marker` (Task 1); `CitationAttribution`, `AttributionKind` (Task 1).
- Produces:
  - `attribute_claim(doc: ExtractedDocument, span: Optional[Tuple[int, int]], llm_marker: Optional[str], citations: Dict[str, str]) -> CitationAttribution`
  - `accept_original(claim_text: str, llm_is_original: bool) -> bool`
  - `MAX_INHERIT_FOLLOWING = 3`, `MAX_INHERIT_PRECEDING = 2`

- [ ] **Step 1: Write the failing tests**

```python
P1 = ("Acute HSV-1 infection involves gingivo stomatitis.^{1} Chronic infection is described.^{1} "
      "An icosadeltahedral capsid surrounds the core. The capsid is composed of 162 capsomers. "
      "The capsid contains channels controlled by tegument proteins.^{2}")
P2 = "In this review, we describe the biology of HSV-1. Herpes vectors are attractive for gliomas."
P3 = ("Vectors were built.^{62–64} They replicate in tumours. They spare neurons. "
      "They are safe. They were tested in mice. Unknown refs exist.^{300}")
CIT = {str(i): f"ref {i}" for i in range(1, 248)}
DOC = make_doc(P1 + "\n\n" + P2 + "\n\n" + P3)
def at(s): i = DOC.text.index(s); return (i, i + len(s))

@pytest.mark.parametrize("sentence, kind, ids, distance", [
    ("Acute HSV-1 infection involves gingivo stomatitis.", "explicit", ["1"], 0),
    ("The capsid is composed of 162 capsomers.", "inherited", ["2", "1"], 1),
    ("An icosadeltahedral capsid surrounds the core.", "inherited", ["1", "2"], -1),
    ("They replicate in tumours.", "inherited", ["62", "63", "64"], -1),
    ("Herpes vectors are attractive for gliomas.", "none", [], 0),   # paragraph boundary
    ("They were tested in mice.", "none", [], 0),                     # 4 sentences away; 300 unknown
])
def test_attribution_by_position(sentence, kind, ids, distance):
    a = attribute_claim(DOC, at(sentence), None, CIT)
    assert (a.kind.value, a.citation_ids, a.sentence_distance) == (kind, ids, distance)

def test_llm_marker_used_when_claim_not_located():
    a = attribute_claim(DOC, None, "49,50", CIT)
    assert (a.kind, a.citation_ids) == (AttributionKind.LLM_MARKER, ["49", "50"])

def test_llm_marker_beats_inheritance():
    assert attribute_claim(DOC, at("They are safe."), "12", CIT).citation_ids == ["12"]

def test_author_year_paper_falls_back_to_llm_marker():          # Review Focus 3
    doc = make_doc("Effects were large (Smith, 2020). Nothing else.")
    a = attribute_claim(doc, (0, 33), "(Smith, 2020)", {"Smith": "Smith, J. (2020)."})
    assert (a.kind, a.citation_ids) == (AttributionKind.LLM_MARKER, ["Smith"])

@pytest.mark.parametrize("text, llm, expected", [
    ("In this review, we describe the biology of HSV-1.", True, True),
    ("As shown in Figure 3, titres rose.", True, True),
    ("Herpes vectors are attractive for gliomas.", True, False),
    ("We found that titres rose.", False, False),
])
def test_accept_original(text, llm, expected):
    assert accept_original(text, llm) is expected
```

- [ ] **Step 2: Run them; they fail.**
- [ ] **Step 3: Implement.**
  - **Sentence end:** `.`, `!` or `?`, plus any closing quote or bracket and any marker directly after it, when the next non-whitespace character is uppercase, a digit or `(`, or is the paragraph end. A `.` between two digits is never an end.
  - **Order of rules:**
    1. Markers inside the claim's own sentence window (start of the first sentence touched to the end of the last, trailing marker included) → `EXPLICIT`.
    2. `resolve_marker(llm_marker)` is non-empty → `LLM_MARKER`.
    3. Within the same paragraph, the nearest following marker 1–3 sentences on and the nearest preceding marker 1–2 sentences back, ids closest first → `INHERITED`, with `sentence_distance` of the closest (positive = following).
    4. Otherwise → `NONE`.
  - Unknown ids are dropped before a marker counts. A marker whose ids are all unknown doesn't count at all.
  - `marker_spans` holds the `(start, end)` of every marker that contributed an id. It is empty for `LLM_MARKER` and `NONE`.
  - `accept_original` is `llm_is_original` and the text matches `\b(we|our|in this (study|review|paper|work|article)|the present study|here we)\b|\b(Fig(ure)?s?\.?|Tables?)\s*\d` (case-insensitive).
- [ ] **Step 4: Run the tests; they pass.**
- [ ] **Step 5: Commit:** `feat(extraction): positional citation attribution with inheritance`

### Task 6: Wire the extractor to the document, the locator and attribution

**Files:**
- Modify:
  - `src/asv/extraction/claim_extractor.py`: `process_pdf`, `extract_citations`, `extract_claims_from_text`, `map_citations_to_claims`, `save_results`; delete `_locate_claim_span`.
  - `src/asv/extraction/llm_client.py:102-164`: prompt and signature.
- Test: `src/asv/extraction/tests/test_claim_extractor.py`, `test_integration.py` (re-point the `extract_text_from_pdf` patches to `extract_document`, and drop the `available_citations` assertion at `:287`); new `test_hsv_cancer_attribution.py`.

**Interfaces:**
- Consumes: Tasks 1–5.
- Produces:
  - In the claims JSON: `claims[*].attribution` and `citation_markers: [{"start", "end", "raw", "ids"}]` (body markers only), plus `summary.attribution: {"explicit", "inherited", "llm_marker", "none"}` counts.
  - `LLMClient.extract_claims_from_chunk(chunk_text, chunk_id, paper_title=None, paper_abstract=None)`, with `available_citations` removed.

- [ ] **Step 1: Write the failing tests** with `extract_document` patched to return `make_doc(P1 + "\n\n" + P2)` and a stub LLM:
  - `test_process_pdf_attributes_from_document_markers`: LLM claims `"The capsid is composed of 162 capsomers."` (marker `None`) and `"Acute HSV-1 infection involves gingivo stomatitis."` (marker `"1"`) come back as `INHERITED ["2","1"]` and `EXPLICIT ["1"]`. Each has `citation_id == citation_ids[0]` and `citation_found is True`.
  - `test_prompt_shows_bracketed_markers_and_no_reference_list`: the captured prompt contains `"stomatitis.[1]"` and not `"Available citations"`.
  - `test_persisted_text_is_document_text_and_offsets_slice_claims`: after `save_results(run_paths=...)`, `claims_text_path()` holds `doc.text`. For each located claim, the letters of `text[start:end]` equal the letters of `claim.text`.
  - `test_original_requires_self_reference`: the LLM flags `"Herpes vectors are attractive for gliomas."` as original, and it comes back with `is_original is False` and kind `none`.
  - `test_summary_counts_attribution_kinds`: `summary["attribution"] == {"explicit": 1, "inherited": 1, "llm_marker": 0, "none": 0}`.
  - `test_hsv_cancer_attribution` (`@pytest.mark.integration`, skip if `pdfs/hsv_cancer.pdf` is missing, no LLM):
    - Reference keys are exactly `"1".."247"`.
    - `refs["81"]` starts with `"al-Rikabi"` and `refs["91"]` with `"van Dillen"`.
    - There are at least 170 body markers.
    - The claim `"Acute HSV-1 infection generally involves gingivo stomatitis."` gets `EXPLICIT ["1"]`.
    - `"The capsid is composed of 162 capsomers"` gets `INHERITED`, with `citation_ids[0] == "2"`.
- [ ] **Step 2: Run them; they fail.**
- [ ] **Step 3: Implement.**
  - `process_pdf` calls `extract_document` once and uses `doc.text` everywhere the PyPDF text was used: title and abstract, reference section, body split, persisted text.
  - Chunk `doc.llm_view(end=body_end)`.
  - Locate each claim with one `ClaimLocator(doc.text)`, using the chunk's `start_pos` as the hint.
  - Assign `attribution` with `attribute_claim`. Set `is_original` only when `accept_original(...)` and the kind is `NONE` or `INHERITED`; then reset the attribution to `NONE`.
  - Derive `citation_id` (first id) and `citation_found` (any ids). `citation_text` is the raw text of the markers in `marker_spans` joined with `", "`, or the LLM marker for `LLM_MARKER`. Derive `citation_details` from the first id with `_parse_citation_details`.
  - In the prompt, replace the reference list with: "Citation markers appear in square brackets, e.g. [12] or [3–5]; copy them exactly into citation_marker."
- [ ] **Step 4: Run** `pytest src/asv/extraction -q` **and** `pytest -q`; both pass. The full suite may still pass at this point because the orchestrator reads only `citation_id`.
- [ ] **Step 5: Commit:** `feat(extraction): deterministic attribution in the extraction pipeline`

### Task 7: One verdict per claim over its cited set

**Files:**
- Modify: `src/asv/core/verdicts.py` (`NotCheckableReason`)
- Create: `src/asv/orchestrator/claim_aggregation.py`
- Test: `src/asv/orchestrator/tests/test_claim_aggregation.py`

**Interfaces:**
- Consumes: `ClaimObject.citation_ids` and `.attribution` (Task 1); `ValidationResult`, `not_checkable`, `ValidationBatch`.
- Produces:
  - `NotCheckableReason.CITATION_INFERRED = "citation_inferred"` and `NotCheckableReason.CITED_SET_INCOMPLETE = "cited_set_incomplete"`
  - `MAX_CITATIONS_PER_CLAIM = 8`
  - `aggregate_claim_verdict(claim: ClaimObject, per_source: Dict[str, ValidationResult]) -> ValidationResult`
  - `collect_per_source(results: Dict[str, list]) -> Dict[str, Dict[str, ValidationResult]]` (claim_id → citation_id → result, read from `ValidationBatch.citation_id`)
  - `aggregate_run(claims: List[ClaimObject], results: Dict[str, list]) -> List[ValidationResult]`, one per claim; uncited results pass through.
  - Every aggregated result sets `validation_metadata["per_source"] = [{"citation_id", "verdict", "not_checkable_reason", "source_url"}]` and `validation_metadata["winning_citation_id"]`, and adds flag `"citation_inherited"` when the kind is `INHERITED`.

- [ ] **Step 1: Write the failing test table.** `S`, `P`, `NS` and `C` are judged results built with one verified `EvidenceSpan`; `NC(r)` is `not_checkable(claim, r, "")`.

| ids (kind) | per_source | expected |
|---|---|---|
| `["43"]` explicit | `43: NS` | the same object (identity) |
| `["43","46","47"]` explicit | `43: NS, 46: S, 47: NS` | `S`, `source_url` = 46's, `winning_citation_id == "46"`, 3 per_source rows |
| same | `43: P, 46: NS, 47: NS` | `P` |
| same | `43: NS, 46: NS, 47: NS` | `NS` |
| same | `43: C, 46: NS, 47: NS` | `C` |
| same | `43: NS, 46: NC(source_download_failed), 47: NS` | `NC(cited_set_incomplete)`, `confidence is None` |
| same | `43: NS` only | `NC(cited_set_incomplete)` |
| same | `43: NC(abstract_only), 46: NC(source_download_failed)` | `NC(abstract_only)` (first cited id's reason) |
| 9 ids explicit | first 8: `NS` | `NC(cited_set_incomplete)` (the 9th is past the cap, so unjudged) |
| `["2","1"]` inherited | `2: NS, 1: C` | `NC(citation_inferred)` |
| same | `2: NS, 1: S` | `S`, with `"citation_inherited"` in flags |

- [ ] **Step 2: Run it; it fails.**
- [ ] **Step 3: Implement, applying these rules in order:**
  1. Any `S` → the best by confidence.
  2. Any `P` → that result.
  3. `INHERITED` → `citation_inferred`.
  4. A single id → identity.
  5. Every cited id judged (not just the capped ones) → `C` if any, else the first `NS`.
  6. Some judged → `cited_set_incomplete`.
  7. None judged → the first cited id's abstention.

  Write explanations for the two new reasons in the house style of `_process_uncited_qualitative`, saying what the user should do.
- [ ] **Step 4: Run the tests; they pass.**
- [ ] **Step 5: Commit:** `feat(orchestrator): aggregate per-source judgments into one claim verdict`

### Task 8: The orchestrator judges each claim against every cited source

**Files:**
- Modify:
  - `src/asv/orchestrator/claim_orchestrator.py`: `_resolution_prepass` (:255), `_audit_references` enrichment (:486-510), `_process_paper_backed_quant` (:952), `_process_cited_qualitative` (:1088), `process_claims` (:215-217), `_save_run_summary` (:1213), `revalidate_citation` (:1383)
  - `src/asv/core/run_paths.py`
- Test: `src/asv/orchestrator/tests/test_multi_citation.py`, reusing the `orchestrator` fixture pattern and `StubTextDownloader` from `test_pipeline_smoke.py`.

**Interfaces:**
- Consumes: Task 7.
- Produces:
  - `RunPaths.claim_verdicts_json() -> Path` (`validation_results/claim_verdicts.json`, shaped `{"schema": 1, "verdicts": [ValidationResult, ...]}`)
  - `ClaimOrchestrator._details_for(citation_id: str) -> Optional[CitationDetails]`
  - `claim_validated` events gain `citation_id`.

- [ ] **Step 1: Write the failing tests:**
  - `test_claim_joins_every_cited_batch_with_that_references_details`: a claim with ids `["43","46"]` gets validated in both batches. The stub downloader's call for `"46"` receives `raw_citation_text == citations["46"]` and details whose `raw_text` is reference 46's, not 43's (D2).
  - `test_substantiated_claim_skips_later_batches`: the stub LLM substantiates in batch 43, and batch 46 has no other claims. The downloader is never called for `"46"`.
  - `test_one_verdict_per_claim`: `claim_verdicts.json` has exactly one entry per input claim, and the run summary's verdict counts sum to `len(claims)` (D3).
  - `test_inherited_claim_is_never_accused`: an inherited claim whose per-source result is `NS` gets `not_checkable` / `citation_inferred` in `claim_verdicts.json`.
  - `test_revalidate_reaggregates`: after `revalidate_citation("46")` flips 46 to `S`, the claim's `claim_verdicts.json` entry is `substantiated`.
- [ ] **Step 2: Run them; they fail.**
- [ ] **Step 3: Implement:**
  - **Details by id:** `_audit_references` fills `self._details_by_id` for every reference: `raw_text` from `citations_dict`, plus `matched_doi`/`matched_title` when verified. `_details_for` falls back to `CitationDetails(raw_text=citations_dict.get(cid))`. Batches call `download_with_resolution(self._details_for(cid), cid, raw)`. Dataset-backed `found_*` batches are unchanged.
  - **Batch membership:** `for cid in claim.citation_ids[:MAX_CITATIONS_PER_CLAIM]`, in both batch builders and in the prepass.
  - **Early skip:** at batch start, drop claims already in `self._substantiated` (a set of claim ids filled whenever a per-source result is `S`). Skip the batch entirely, without downloading, if none remain.
  - **Finish:** after Step 4, `verdicts = aggregate_run(claims, results)`. Write `claim_verdicts.json`, and compute `_save_run_summary`'s verdict and reason counts from `verdicts`, grouped by each claim's routing group, instead of flattening batches. Batch result files keep their shape; they are now the per-source record.
  - **Retry:** `revalidate_citation` picks claims with `citation_id in c.citation_ids`, merges as today, then recomputes those claims from `collect_per_source` over the on-disk result files and rewrites their entries.
- [ ] **Step 4: Run** `pytest src/asv/orchestrator -q` **and** `pytest -q`; both pass.
- [ ] **Step 5: Commit:** `feat(orchestrator): judge claims against every cited source`

### Task 9: API and UI show one verdict and how the citation was attributed

**Files:**
- Modify:
  - `apps/api/services/read_model.py:185-290`
  - `apps/api/schemas.py:34-38` (`CitationRef`)
  - `apps/web/src/api/types.ts` (regenerated)
  - `apps/web/src/lib/verdict.ts`
  - `apps/web/src/components/ClaimDetailDrawer.tsx`
- Test: `apps/api/tests/test_read_model.py`

**Interfaces:**
- Consumes: `claim_verdicts.json` (Task 8); `ClaimObject.attribution` (Task 1).
- Produces: `CitationRef.ids: List[str] = []`, `CitationRef.attribution: Optional[str] = None`, `CitationRef.sentence_distance: Optional[int] = None`.

- [ ] **Step 1: Write the failing tests:**
  - `test_claim_verdicts_file_is_authoritative`: a run fixture whose batch files hold per-source `NS` for a claim, while `claim_verdicts.json` says `S`, gives a row with `result.verdict == "substantiated"`. `batch.citation_id` equals `winning_citation_id`.
  - `test_citation_ref_carries_all_ids_and_kind`: `row.citation.ids == ["2","1"]` and `row.citation.attribution == "inherited"`.
  - The existing read-model tests on fixtures without `claim_verdicts.json` pass unmodified (Review Focus 5).
- [ ] **Step 2: Run them; they fail.**
- [ ] **Step 3: Implement.**
  - In `build_claim_rows`: when `claim_verdicts_json()` exists, results come from it and `batch_ref` is the batch for `winning_citation_id`, else the first cited id. Otherwise keep today's path.
  - Run `npm run gen-types` (API on :8000).
  - In `verdict.ts`, label `citation_inferred` "Citation inferred from context" and `cited_set_incomplete` "Not every cited source could be checked".
  - The drawer lists all cited ids. For `inherited`, it adds: "This sentence has no citation of its own; ASV used the citation {n} sentence(s) {later|earlier} in the paragraph."
- [ ] **Step 4: Run** `pytest apps/api -q` **and** `cd apps/web && npm run build`; both pass.
- [ ] **Step 5: Commit:** `feat(api,web): one verdict per claim; show citation attribution`

### Task 10: Measure on the reference paper and update the docs

**Files:**
- Create: `src/asv/extraction/attribution_audit.py` (logic); `scripts/audit_attribution.py` (thin CLI; `scripts/` has no test path in `pytest.ini`)
- Modify: `docs/README.md` (row 1.7), `CLAUDE.md` (Stage 1, the verdict reasons, outputs), `src/asv/extraction/README.md`, `scripts/README.md`, this file (status)
- Test: `src/asv/extraction/tests/test_attribution_audit.py`

**Interfaces:**
- Consumes: the claims JSON fields from Task 6.
- Produces:
  - `audit_claims(claims_json: Dict[str, Any]) -> Dict[str, Any]`
  - `format_report(audit: Dict[str, Any]) -> str`
  - `python scripts/audit_attribution.py <run_dir>`, which prints:
  - claims, and located %
  - counts by attribution kind
  - multi-citation share
  - LLM-versus-deterministic agreement (exact / overlap / disjoint) for claims that have both
  - the reference key count and any non-sequential keys

- [ ] **Step 1: Write the failing test.** On a 4-claim synthetic claims dict (one each of explicit, inherited, llm_marker and none, with one unlocated), `format_report(audit_claims(d))` contains `"explicit: 1"`, `"inherited: 1"`, `"located: 75.0%"` and `"disjoint: 0"`.
- [ ] **Step 2: Run it; it fails.** **Step 3: Implement it.** **Step 4: Run it; it passes.**
- [ ] **Step 5: Run the pipeline end to end:** `python scripts/run_pipeline.py pdfs/hsv_cancer.pdf`, then `python scripts/audit_attribution.py runs/<new run>`. Acceptance:
  - reference keys are exactly 1–247
  - located is at least 95% (was 72%)
  - attributed (explicit + llm_marker + inherited) is at least 80% (was 19%)
  - explicit + llm_marker is at least 40%
  - disjoint is 0, or each case has been reviewed by hand
  - `pytest -q` is green

  Record the numbers and the run's verdict and reason table in this file's status section.
- [ ] **Step 6: Update the docs** listed above with the measured numbers. Mark VP 1.7 ✅ or 🟡 by those numbers.
- [ ] **Step 7: Commit:** `docs: citation attribution measured on hsv_cancer`

## Status

Not started. Plan written 2026-11-01.
