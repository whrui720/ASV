# Source Acquisition — Current State, Failure Modes, and Improvement Plan

**Status:** Phases 0–4 implemented 2026-09-23. See
[§10 Implementation status](#10--implementation-status) for what shipped, what
was measured, and the endpoint facts that turned out to be wrong when checked
against the live services.
**Date:** 2026-09-01 (analysis), 2026-09-23 (implementation).
**Scope:** how ASV finds and downloads the two kinds of evidence it validates against —
*text sources* (the cited papers) and *data sources* (tabular datasets) — why the hit rate
is low, and what to do about it.

Everything in the "Measured today" and "Failure modes" sections is derived from the
manifests and logs already in `runs/`, not from guesswork. Reproduce with the aggregation
snippet in [Appendix A](#appendix-a--how-the-numbers-were-computed).

---

## TL;DR

- **Text-source acquisition succeeds on ~31–47% of citation batches**, and the rate swings
  run-to-run *on the same PDF* (24/51 on 2026-07-04 → 16/51 on 2026-07-06). That variance is
  itself a bug signal: nothing is cached, nothing is retried, nothing is rate-limited.
- **80% of failed fetches are HTTP 403** from publisher hosts (`journals.asm.org`,
  `onlinelibrary.wiley.com`, `cell.com`, `academic.oup.com`, …). We are being bot-blocked,
  not paywalled-in-the-legal-sense — a real browser with the same (or no) credentials
  usually renders those pages.
- **The candidate list is one URL deep for 63% of batches** (32/51). One 403 kills the batch.
  This is the single highest-leverage fix: the resolution cascade *stops at the first API
  that returns anything* instead of unioning all of them.
- **Every fallback we built is dead in practice.** Browser retry: 0 invocations in the last
  recorded run (the code landed after it). Institutional cookies: 0 attempts, ever. Paywall
  login prompt: never fires, because it looks for publisher domains in *bibliography text*
  rather than in resolved URLs. Zenodo/Figshare/HuggingFace/Scholar browser search: returns
  "no candidate links found" 100% of the time (they are client-rendered SPAs).
- **Some "successes" are worse than failures.** 13 of 16 wins in the latest run were HTML,
  10 of them Nature landing pages — abstract + reference list only. They clear the 200-char
  gate and feed RAG a document that does not contain the claim's evidence.
- **Biggest missed opportunity:** we never query **Europe PMC**, **PubMed Central OA**, or
  **OpenAlex** — the three services that would most directly fix a biomedical corpus like
  `hsv_cancer.pdf`. Europe PMC already appears in our *successful* rows only because
  Unpaywall happened to surface it.

---

## 1. What we do today — text sources (cited papers)

### 1.1 Resolution: `AcademicPaperFinder.find_urls()`

`src/asv/sourcefinder/academic_paper_finder.py`. Input is the raw bibliography string for a
`citation_id`; output is a ranked list of candidate URLs.

| # | Step | Trigger | Notes |
|---|---|---|---|
| 0 | LLM citation parse | always | Gemini parses `{title, first_author, year, journal, doi}`. Cached per raw string. |
| 1 | Regex DOI → `_resolve_from_doi` | DOI matches `10.\d{4,}/…` | Unions Unpaywall + Semantic Scholar + CrossRef for that DOI. |
| 2 | LLM-parsed DOI → `_resolve_from_doi` | step 1 empty | Catches DOIs the regex misses. |
| 3 | Semantic Scholar title search | steps 1–2 empty | Also recovers a DOI from non-OA hits and re-feeds it to Unpaywall/CrossRef. |
| 3b | CrossRef `query.bibliographic` | still empty | Free, no key, ~140M works. Returns top-1 DOI only. |
| 4 | Google Scholar via Playwright | still empty | LLM ranks the links scraped off the results page. |

**Ranking inside step 1:** Unpaywall's `oa_locations` are sorted
`(host_type != "repository", no url_for_pdf)` — repository mirrors (PMC, arXiv, institutional
repos) before publisher URLs, PDFs before landing pages. CrossRef contributes only `link[]`
entries that look like PDFs; the DOI landing URL is deliberately excluded.

### 1.2 Download: `TextDownloader.download_with_resolution()`

`src/asv/sourcefinder/text_downloader.py`. Four phases, first success wins:

1. **`direct`** — `citation_details.url` if the extractor already populated one.
2. **`open_access`** — iterate `find_urls()` candidates, `requests.get` each.
3. **`institutional_cookies`** — only if `INSTITUTIONAL_COOKIES` is set, and only against
   `https://doi.org/{doi}`.
4. **`browser`** — replay up to 5 already-failed URLs through Playwright's
   `APIRequestContext`, which shares storage state (and therefore login cookies) with the
   visible browser.

Each fetched payload goes through `_process_bytes`: magic-byte format sniff → write to
`runs/*/text_sources/` → extract text (PDF: PyMuPDF → pdfminer.six → pypdf; HTML: strip
chrome, then take the first semantic container) → **200-char usable-text gate**. Below the
gate the file is deleted and `downloaded=False` is returned so the cascade continues.

Every attempt is recorded in `runs/*/text_sources/_manifest.json` with its `source` label,
so the whole cascade stays auditable after the files are cleaned up post-batch.

## 2. What we do today — data sources (datasets)

`DatasetFinder.find_dataset(claim_text, claim_id)` — reached only from
`_process_uncited_quantitative`:

1. **Reuse check** — the LLM is asked whether any already-downloaded dataset covers the new
   claim; reused at confidence > 0.75.
2. **Search** — `data.gov` CKAN `package_search`, then Kaggle (`kaggle` package, needs
   credentials), then — only if both returned nothing — browser scraping of Zenodo, Figshare,
   and HuggingFace Datasets.
3. **Rank** — `_rank_candidates` returns `max(candidates, key=score)`, where every score is a
   hardcoded constant (0.7 for API hits, 0.65 for browser hits). It is first-source-wins; the
   docstring still says *"In production, would use LLM to re-rank."*

`DatasetDownloader.download` does one session GET, sniffs the format from magic bytes +
Content-Type + URL, and parses CSV/JSON/XLSX/XLS from memory. Non-tabular payloads are
rejected with `"URL is not tabular data (detected: …)"`. The `Accept` header deliberately
omits `application/json` so DOI URLs cannot content-negotiate into CrossRef metadata.

## 3. What we ask the user for

| Credential | Required? | Obtained how | What it unlocks | Reality check |
|---|---|---|---|---|
| `GEMINI_API_KEY` | yes | Google AI Studio | all LLM steps incl. citation parsing | fine |
| `UNPAYWALL_EMAIL` | strongly recommended | any real email, no signup | **the entire Unpaywall step is skipped without it** | fine, but a silent `logger.debug` skip is too quiet for something this load-bearing |
| `SEMANTIC_SCHOLAR_API_KEY` | optional | free, instant approval | dedicated rate limits | worth having; the shared pool 429s under a 51-batch run |
| `GOOGLE_FACT_CHECK_API_KEY` | optional | Google Cloud | truth-table branch | unrelated to downloads |
| `KAGGLE_USERNAME` / `KAGGLE_KEY` | optional | kaggle.com → Settings → API token | Kaggle dataset search | fine |
| `INSTITUTIONAL_COOKIES` | optional | **manual DevTools copy-paste**, per domain | authenticated publisher fetch | effectively unusable — see [F5](#f5-the-institutional-auth-paths-are-both-dead) |
| Interactive browser login | optional | non-headless Chromium tab + blocking `input()` | cookies bridged into every `requests.Session` | good design, but the trigger almost never fires — see [F6](#f6-the-paywall-login-checkpoint-almost-never-fires) |

The `/credentials` slash command (`.claude/commands/credentials.md`) walks the user through
all of these.

---

## 4. Measured today

From `runs/*/text_sources/_manifest.json` and `runs/*/datasets/_manifest.json`, all on the
same input (`pdfs/hsv_cancer.pdf`):

| Run | Batches | Downloaded | Rate | Winning formats |
|---|---|---|---|---|
| `20260703_162705` | 37 | 18 | 49% | 9 pdf / 9 html |
| `20260704_103453` | 51 | 24 | 47% | 16 pdf / 8 html |
| `20260704_110320` | 51 | 21 | 41% | 3 pdf / 18 html |
| `20260706_192057` | 51 | **16** | **31%** | 3 pdf / 13 html |

Latest run, attempt-level:

```
total batches                 51
zero candidates found          2   (4%)  — nothing resolved at all
candidates found, all failed  33   (65%)
downloaded                    16   (31%)

candidates per batch:  1 → 32 batches   2 → 16   3 → 1   0 → 2

failed-attempt error classes:
  41  403 Forbidden
   7  too-little-text gate (<200 chars)
   2  400 "No TDM Client Token was found in the request"  (Wiley)
   1  404
```

Top 403 hosts: `journals.asm.org` (7), `jvi.asm.org` (6), `onlinelibrary.wiley.com` (5),
`doi.org` (5), `cell.com` (3), `academic.oup.com` (3), `ashpublications.org` (2),
`aacrjournals.org` (2), `ingentaconnect.com` (2), `api.wiley.com` (2).

Winning hosts: `nature.com` ×10 (all HTML), `europepmc.org` ×3 (all PDF),
`annualreviews.org`, `link.springer.com`, `doi.org`, `scholar.googleusercontent.com`.

The **downward drift across identical runs** (49% → 47% → 41% → 31%) is the tell: we are
progressively tripping publisher rate limits and bot heuristics with no backoff, no cache,
and no per-host politeness.

---

## 5. Failure modes, ranked by expected recovered yield

### F1. The candidate list is one URL deep
**Evidence:** 32/51 batches had exactly one candidate; 2 had zero; only 17 had ≥2.
**Cause:** `find_urls` is a *first-hit-wins* cascade. Steps 2, 3, 3b, and 4 are each guarded
by `if not candidates`. If Unpaywall returns a single publisher URL that 403s, the Semantic
Scholar title search, the CrossRef bibliographic resolver, and Google Scholar are never
consulted — even though they might have found a PMC mirror.
**Fix:** turn the cascade into a **union-then-rank**. Query every resolver (cheap ones
unconditionally, expensive ones when the pool is thin), dedupe by normalised URL, then sort
by a real preference function: OA repository PDF > OA repository landing > publisher PDF >
publisher landing > search-engine guess. Cap the pool at ~8 and try them all.
**Expected gain:** large. Most of the 33 failures are batches where a mirror plausibly
existed but was never asked for.

### F2. 403 Forbidden is 80% of all failures
**Cause:** publishers block datacentre / plain-`requests` traffic. Our UA string is
browser-shaped but everything else (no `Referer`, no `Sec-Fetch-*`, no cookie jar, no TLS
fingerprint) says "script". `jvi.asm.org` and `journals.asm.org` block on sight.
**Fixes, in order of cost:**
1. **Prefer OA aggregators over publishers.** See [§6](#6-apis-worth-adding) — Europe PMC
   and PMC OA give machine-readable full text for exactly the biomedical hosts blocking us.
2. **Actually use the browser fallback** (it exists, it has just never run — see F4).
3. **Send a plausible `Referer`** (`https://doi.org/{doi}` or the journal TOC) plus
   `Sec-Fetch-Mode` / `Sec-Fetch-Site`. Cheap, occasionally sufficient.
4. **Register for publisher TDM programmes.** The two `400 No TDM Client Token` errors are
   Wiley telling us exactly which header it wants (`Wiley-TDM-Client-Token`). Elsevier and
   Springer Nature have equivalent free developer keys.
5. **EZproxy rewriting** — see [§7](#7-institutional-access-done-properly).

### F3. "Successful" downloads are often abstract-only landing pages
**Evidence:** 13/16 wins were HTML; 10 were `nature.com`. One batch (`citation_108`) has a
`winning_url` ending in `.pdf` but `format: "html"` — Nature served the landing page for a
`.pdf` request, we sniffed HTML correctly, extracted the abstract, and called it a win.
**Why it matters:** RAG then searches a document that does not contain the evidence, and the
claim gets a confident-looking verdict built on an abstract. This is a *worse* outcome than
`download_successful: false`, which at least reports honestly.
**Fix:**
- Raise the gate for HTML from 200 chars to a content-shaped test: require either a
  section/heading structure typical of a full text, or a length floor around 3–5k chars.
- Add a **paywall-phrase detector** on the extracted text (`"Access through your
  institution"`, `"Buy this article"`, `"Subscribe to journal"`, `"Rent this article"`),
  reusing the phrase list already in `BrowserSearcher.is_paywalled`.
- Record `text_chars` and a `content_quality` verdict (`full_text` / `abstract_only` /
  `rejected`) in `SourceManifestEntry`, and let `ProcessQualitative` refuse to run RAG on
  `abstract_only`.

### F4. Every fallback we built is dead

| Fallback | Status | Why |
|---|---|---|
| Browser retry of failed URLs | **never executed** — 0 `"Browser retry"` lines in the 2026-07-06 log, across 33 failed batches | the code landed in `79a823f` (2026-08-31), after the last recorded run. Untested end-to-end. |
| `institutional_cookies` | **0 attempts across every run** | requires `INSTITUTIONAL_COOKIES` to be set; and even then it only ever tries `https://doi.org/{doi}`, never the publisher URLs that actually 403'd |
| Zenodo / Figshare / HuggingFace browser search | **0 links, 100% of the time** | client-rendered SPAs; `wait_until="domcontentloaded"` returns before results render, so `_extract_candidate_links` sees an empty shell |
| Google Scholar | **"no candidate links found"** on every query | same timing problem plus Scholar's consent/CAPTCHA interstitial. Scholar is also explicitly hostile to automation. |

**Fix:** re-run the pipeline now that the browser retry exists and measure it. Replace all
three dataset SPA scrapes with their **free JSON APIs** (§6) — scraping them was never
necessary. Retire the Google Scholar scrape or gate it behind an explicit opt-in flag.

### F5. The institutional auth paths are both dead
`INSTITUTIONAL_COOKIES` asks the user to open DevTools, identify the right session cookies by
name, hand-assemble JSON, and redo it every 7–30 days. It is keyed by exact netloc, so
`nature.com` silently misses `www.nature.com`. Nobody will maintain this.
**Fix:** demote it to an escape hatch. The Playwright login flow already does the same job
better — it just needs to fire (F6) and to be persisted (`context.storage_state()` written to
disk and reloaded on the next run, so login survives across runs instead of being re-prompted
every time).

### F6. The paywall login checkpoint almost never fires
`_setup_browser_searcher` decides whether to prompt for login by substring-matching
`KNOWN_PAYWALL_DOMAINS` against **the raw bibliography text**. Bibliography entries contain
journal names, not URLs. The 2026-07-06 run logged
`No known paywall domains detected in citations — browser ready (no login needed)` — and then
403'd 41 times on `wiley.com`, `cell.com`, `oup.com`, and `asm.org`.
**Fix:** split resolution from download. Run a **resolution pass over all citations first**
(cheap — it is only API calls), collect the resolved candidate hosts, intersect with
`KNOWN_PAYWALL_DOMAINS`, *then* prompt for login once with an accurate list. Bonus: the
resolution pass parallelises and caches cleanly, and it gives the web UI a real progress bar.

### F7. No caching, no retry, no rate limiting
Every run re-resolves and re-fetches the same 51 citations from scratch. A 403 is terminal —
no backoff, no second attempt, no `Retry-After` handling. There is no per-host delay, so we
hammer `asm.org` seven times in a burst.
**Fix:**
- A content-addressed **HTTP cache** keyed on URL under `~/.cache/asv/` (or `runs/_cache/`),
  storing body + headers + fetch timestamp. Makes reruns fast, reproducible, and polite.
- `urllib3.util.Retry` on the sessions for 429/500/502/503/504, with exponential backoff and
  `Retry-After` respected.
- A per-host token bucket (~1 req/sec, configurable) shared across all sessions.
- **Expected side effect:** the 49%→31% drift disappears, and runs become deterministic
  enough to A/B test every other fix in this document.

### F8. Citation parsing degrades the query before it reaches any API
In `runs/*/text_sources/_manifest.json`, `citation_details.doi` is `null` for **every** entry,
and `authors` is mangled: `["Lerner AM.Infections with herpes simplex virus.In: Adams RD"]`.
The upstream PDF text extraction is dropping spaces between reference fields
(`"Gene Therapy2002;9: 584–591"`), so both the LLM parser and the CrossRef bibliographic
query receive corrupted input.
**Fix:** normalise reference strings before parsing — re-insert spaces at lowercase→uppercase
and letter→digit boundaries, and repair the `â€™` / `â€"` mojibake visible in the manifest
(that is UTF-8 being read as cp1252). Then feed CrossRef structured `query.author` +
`query.container-title` + `query.bibliographic` instead of one blob, and check the returned
`score` / title similarity before accepting the top hit.

### F9. Some references are unresolvable by design, and we count them as failures
`"Lerner AM. Infections with herpes simplex virus. In: Harrison's Principles of Internal
Medicine. McGraw-Hill, 1980"` is a **book chapter**. So is
`"Roizman B, Knipe DM. Herpes Simplex Viruses and their Replication. Lippincott, 2001."`
No DOI, no OA copy, no amount of retry will fix these.
**Fix:** classify citation *kind* during parsing (journal article / book / chapter /
conference / web / dataset / personal communication) and give books a distinct terminal
status (`unresolvable_source_type`) rather than `download failed`. This makes the headline
metric honest and stops us burning queries on textbooks. Optionally route books to the Open
Library / HathiTrust / Google Books APIs for at least snippet-level checking.

### F10. Dataset finding is barely functional
- `find_dataset` searches **data.gov and Kaggle with the raw claim sentence truncated to 100
  chars**. For a virology paper this cannot work — the corpora do not overlap at all.
- `_rank_candidates` is `max(score)` over hardcoded constants → first source wins.
- The 2026-07-03 dataset manifest shows **12/14 "successes", all `format: json`, all from
  `doi.org`** — those were CrossRef bibliographic records, not data. The `Accept`-header fix
  closed that specific hole, but `_sniff_format` still accepts *any* `application/json`
  payload as a dataset, so any other JSON-serving endpoint slips through.
- `MAX_FILE_SIZE_MB = 500` and `MIN_RELEVANCE_SCORE = 0.6` are **dead config** — referenced
  nowhere in the codebase. There is no streaming and no size guard; a large file is pulled
  fully into memory.
**Fix:** query registries that actually index scientific data (DataCite, Dryad, Zenodo,
Figshare, OpenAIRE — §6); build the search query from the claim's *entities and measures*
rather than the raw sentence; add a real LLM re-rank; add a **tabular shape check** (≥1 row,
≥2 columns, parseable header) before declaring success; enforce `MAX_FILE_SIZE_MB` with a
streaming `Content-Length` check.

---

## 6. APIs worth adding

Ordered by expected impact on *this* corpus. All are free; the "key" column says whether
registration is needed.

### Tier 1 — add these first

| Service | Endpoint | Key | Why it matters here |
|---|---|---|---|
| **Europe PMC** | `https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=…&format=json`, then `…/{source}/{id}/fullTextXML` | none | Biomedical-first, and — critically — serves **machine-readable full-text XML** for the OA subset instead of a PDF we have to parse. Our only clean PDF wins already came from `europepmc.org`. For an HSV / oncolytic-virus paper this is the single highest-yield addition. |
| **PubMed Central OA + ID Converter** | `https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/?ids={doi}` → PMCID, then E-utilities `efetch` | optional NCBI key raises the rate limit | Converts DOIs Unpaywall misses into PMCIDs. Directly targets the `asm.org` / `aacrjournals.org` 403s, most of which have PMC deposits. |
| **OpenAlex** | `https://api.openalex.org/works/doi:{doi}` (add `?mailto=` for the polite pool) | none | ~250M works, better coverage than Semantic Scholar for older/obscure refs, exposes `best_oa_location` plus every `location` with its `pdf_url`. Also gives structured metadata for reference disambiguation (F8) and fuzzy title matching for DOI-less refs. A strong complement to — or replacement for — step 3b. |
| **Zenodo REST** | `https://zenodo.org/api/records?q=…` | none | Replaces the browser scrape that returns zero results 100% of the time. Direct file-download URLs come back in the response. |
| **Figshare REST** | `https://api.figshare.com/v2/articles/search` | none | Same — replaces a broken scrape. |
| **HuggingFace Datasets** | `https://huggingface.co/api/datasets?search=…` | none | Same. |
| **DataCite** | `https://api.datacite.org/dois?query=…` | none | The DOI registry for *datasets*, as CrossRef is for articles. This is the piece missing from `DatasetFinder`: it indexes the repositories where scientific data actually lives. |

### Tier 2 — publisher TDM programmes (free, but require registration)

These convert 403s into 200s for exactly the hosts blocking us. Each is a free developer
registration whose terms permit text/data mining for research.

| Publisher | What to get | Header / usage |
|---|---|---|
| **Wiley TDM** | client token | `Wiley-TDM-Client-Token` against `api.wiley.com/onlinelibrary/tdm/v1/articles/{doi}`. We are already receiving `400 No TDM Client Token was found in the request` — the server is asking us for this by name. |
| **Elsevier / ScienceDirect** | API key at `dev.elsevier.com` | `X-ELS-APIKey`. Full-text XML for entitled content, abstracts otherwise. Entitlement generally requires the request to originate from the institution's IP range or carry an institutional token. |
| **Springer Nature** | API key at `dev.springernature.com` | `openaccess` endpoint returns OA full text; `meta` returns metadata. Would cover a chunk of our `link.springer.com` / `nature.com` traffic — the same hosts currently handing us abstract-only HTML (F3). |
| **CORE** | free API key at `core.ac.uk` | Aggregates ~300M OA papers **from repositories**, which is precisely the mirror layer that routes around publisher blocks. A good breadth-of-last-resort before falling back to a browser. |

### Tier 3 — non-article and statistical claims

`arXiv` (preprints, no key), `OpenAIRE` and `Dryad` (research data), `Open Library` /
`HathiTrust` / `Google Books` (the textbook references from F9), and — for quantitative
uncited claims citing public statistics rather than a dataset file — `World Bank`,
`Eurostat`, `WHO GHO`, `OECD`, and `FRED` (key required). `data.gov` should stay, but its
CKAN endpoint needs re-verifying: it returned 404 throughout the 2026-06-22 run.

---

## 7. Institutional access, done properly

The user is at `umich.edu`, which — like nearly every research university — runs **EZproxy**.
EZproxy access is a hostname rewrite, not a cookie hack:

```
https://www.sciencedirect.com/science/article/pii/X
→ https://www-sciencedirect-com.proxy.lib.umich.edu/science/article/pii/X
```

**Proposal:** add an optional `EZPROXY_HOST` setting (e.g. `proxy.lib.umich.edu`). When set,
`download_with_resolution` gains a fifth phase: rewrite each 403'd publisher URL through the
proxy host and retry — through the **Playwright context**, so the user's SSO session applies.
Combined with persisted `storage_state()` (F5), the user logs in via their institution's SSO
once and every subsequent run inherits it.

This is strictly better than `INSTITUTIONAL_COOKIES`: it uses the sanctioned access path, it
survives cookie rotation, and it never asks the user to paste secrets into a `.env`.

**Guardrails to build alongside it**, because bulk downloading through a proxy is exactly what
gets a university's access suspended: cap requests per host per run, enforce the per-host rate
limit from F7, honour publishers' stated TDM rules, and keep the proxy path opt-in with a
one-line statement in the docs that the user is responsible for complying with their
library's terms.

---

## 8. Would MCP tools help?

Partly — they are the wrong shape for the hot path, and the right shape for two specific jobs.

**Why not for the batch pipeline.** A run resolves ~51 citations and issues a few hundred HTTP
requests. That work is a tight loop of well-defined REST calls where we want caching, backoff,
and per-host rate limiting under our own control. Routing it through an MCP server adds a hop
and an LLM round-trip per call for no gain in success rate. The Tier-1 APIs in §6 should be
plain `requests` code inside `sourcefinder/`.

**Where MCP genuinely helps:**

1. **`claude-in-chrome` (already available in this environment).** It drives the user's *real*
   Chrome — with their real, already-authenticated institutional SSO session and a real
   browser TLS/header fingerprint. That is a materially better answer to F2/F5 than anything
   `requests` can do, and it requires no credential handling on our side at all. Best used as
   a **human-in-the-loop rescue lane**: after a run, hand the operator the list of failed
   batches and let an agent walk it in their browser. Not appropriate for unattended bulk
   fetching.
2. **A Playwright MCP server** (e.g. Microsoft's `@playwright/mcp`) as a supported alternative
   to our hand-rolled `BrowserSearcher`. It would replace ~370 lines of Playwright plumbing
   with a maintained server, and it handles SPA waiting properly — exactly what broke the
   Zenodo/Figshare/HuggingFace scrapes (F4). Worth evaluating *if* we keep browser search at
   all after moving those three to their JSON APIs.
3. **A fetch/HTTP MCP server** for ad-hoc "why did this one URL fail" debugging during
   development. Convenience, not throughput.

There are community MCP servers advertising arXiv / PubMed / Semantic Scholar access. I have
not verified any of them, and I would not put an unaudited third-party server in the
credentialed path of this pipeline — each is a thin wrapper over a public API we can call
directly in ~30 lines, with none of the supply-chain question.

**Recommendation:** direct APIs for the pipeline; `claude-in-chrome` as an operator-driven
rescue lane for the residual failures; evaluate Playwright MCP only as a maintenance
reduction, not as a capability gain.

---

## 9. Proposed sequencing

Each phase is independently shippable and independently measurable against the same
`hsv_cancer.pdf` baseline (31% today).

**Phase 0 — make the metric trustworthy (prerequisite for everything else)**
- HTTP cache + retry/backoff + per-host rate limit (F7).
- Record `text_chars` and `content_quality` in `SourceManifestEntry` (F3).
- Classify citation kind; give books a terminal `unresolvable_source_type` (F9).
- Re-run the pipeline as-is for a clean, cache-backed baseline — and to finally exercise the
  browser retry that has never run (F4).

**Phase 1 — resolution breadth** *(expected: the largest single jump)*
- Union-then-rank instead of first-hit-wins (F1).
- Add Europe PMC, the PMC ID Converter, and OpenAlex to the resolver pool (§6 Tier 1).
- Normalise reference strings before parsing; structured CrossRef queries (F8).

**Phase 2 — beat the 403s**
- Prefer OA aggregators over publisher URLs in the ranking function.
- `Referer` / `Sec-Fetch-*` headers.
- Register Wiley TDM, Springer Nature, Elsevier, and CORE keys (§6 Tier 2).
- Fix the paywall-detection trigger to run on resolved hosts, not bibliography text (F6).

**Phase 3 — institutional access**
- Persist Playwright `storage_state()` across runs.
- Optional `EZPROXY_HOST` rewrite phase, with the rate guardrails from §7.
- Demote `INSTITUTIONAL_COOKIES` to a documented escape hatch.

**Phase 4 — datasets**
- Replace the three SPA scrapes with the Zenodo / Figshare / HuggingFace JSON APIs.
- Add DataCite, Dryad, and OpenAIRE (§6).
- Entity-driven query construction, a real LLM re-rank, a tabular shape check, and
  `MAX_FILE_SIZE_MB` enforced with streaming (F10).

**Phase 5 — residual rescue**
- `claude-in-chrome` operator lane over the still-failing batches (§8).

---

## 10 — Implementation status

Implemented 2026-09-23. Ordered as §9 proposed; the phase numbers below are that
plan's.

### What shipped

| Item | Where | Note |
|---|---|---|
| **F7** HTTP cache, retry/backoff, per-host rate limit | `sourcefinder/polite_http.py` (new) | One process-wide host clock shared by every session. The audit, the resolver and the downloader each had their own, so "1 req/host/sec" was really three. Also a **default 25s timeout** — `requests` waits forever, and a resolver asking eight services per citation has eight chances to hang the run — with timeouts deliberately *not* retried, and a per-host circuit breaker that expires after a cooldown rather than killing the host for the run. |
| **F1** Union-then-rank resolution | `academic_paper_finder.find_candidates` | Every resolver is asked; the pool is deduped and sorted by *kind*, not by who answered first. |
| **§6 Tier 1** Europe PMC, PMC ID converter, NCBI efetch, OpenAlex, CORE, arXiv | `sourcefinder/fulltext_apis.py` (new) | Europe PMC/efetch return JATS, which ranks above every PDF: no layout to reconstruct, no landing-page chrome. |
| **§6 Tier 2** Wiley TDM, Elsevier, Springer Nature | `fulltext_apis.publisher_tdm` + `core/credentials.auth_headers_for` | Headers are keyed on *host*, so a TDM link carries its token whichever resolver surfaced it. Silent without a key rather than emitting a URL that is certain to 400. |
| JATS/XML format detection and extraction | `text_downloader._extract_xml_text` | Section titles are preserved on their own lines because the content gate keys off IMRaD headings; `<ref-list>` is dropped. |
| **F2** `Referer` / `Sec-Fetch-*` on publisher fetches | `polite_http.PoliteSession.get(browser_headers=True)` | Measurably works — see below. |
| **F6** Login checkpoint keyed on resolved hosts | `claim_orchestrator._resolution_prepass` + `_paywall_login_checkpoint` | Resolution now runs as step 0b over every cited source, before any claim is processed. It is cached, so the batches read it back — a reordering, not extra work. |
| **F8** Reference-string repair | `sourcefinder/reference_text.py` (new) | Applied before the LLM parse, before Crossref, and in the Tier 0.6 audit. |
| **F5** Suffix-matched institutional cookies | `academic_paper_finder.fetch_with_cookies` | A `nature.com` entry no longer silently misses `www.nature.com`. |
| Title verification on every search hit | `fulltext_apis.title_matches` | Not in the plan, but the plan's own fix created the need. Europe PMC, OpenAlex, Semantic Scholar and Crossref title searches all return a best row whether or not it is the paper. Unverified, that row's DOI propagates into every other resolver and ASV judges a claim against the wrong paper *behind a resolvable source URL* — a false accusation with a citation attached. |
| **§7** EZproxy rewrite phase | `text_downloader.ezproxy_url` + phase 5 | Opt-in via `EZPROXY_HOST`, fetched through the browser context so SSO applies, capped at `EZPROXY_MAX_PER_RUN` (40). |
| **F10 / Phase 4** Zenodo, Figshare, DataCite, HuggingFace JSON APIs | `dataset_finder` | Replaces three SPA scrapes that returned zero links 100% of the time. |
| **F10** Entity-driven queries, real LLM re-rank, tabular shape check, size cap | `dataset_finder`, `dataset_downloader` | `MAX_FILE_SIZE_MB` is enforced by streaming; it was dead config. The re-rank may reject every candidate. |
| **§3** Credentials editable in the UI | `core/credentials.py` (new), `/api/config/credentials`, `ConfigPage` | One catalogue drives the API, the form and the health view. Secrets are write-only over HTTP. |

### Six things the analysis got wrong, found by calling the services

1. **Europe PMC full text is `/webservices/rest/{PMCID}/fullTextXML`** — the
   PMCID alone in the path. The `/{source}/{id}/` form documented for other
   operations returns 404 for every record tested.
2. **Europe PMC answers `500`, not `404`, for an article outside its OA
   subset.** This briefly made things *worse*: 500 is retryable, so the circuit
   breaker tripped three non-OA articles into a run and disabled the
   highest-yield source for everything after it. The breaker now counts only
   429s, and the `fullTextXML` candidate is gated on the record's `inEPMC` flag.
3. **Figshare's article search is POST with a JSON body.** The GET form returns
   404 with a routing error that reads like "no results".
4. **Zenodo's API returns 403 to the Chrome User-Agent and 200 to a descriptive
   research agent** — the exact opposite of what publishers want. The UA is now
   chosen per service: `BROWSER_UA` for pages meant for humans,
   `api_user_agent()` for registries.

5. **OpenAlex without a `mailto` is not slow, it is unusable.** §6 lists the
   parameter as a politeness nicety ("add `?mailto=` for the polite pool").
   Measured: an anonymous DOI lookup **returned 200 after 90 seconds**; the same
   call with an address answers in under a second. It throttles by *delaying*,
   which a read timeout cannot catch because bytes are still arriving — so the
   only choices are to stall the run or to skip the service. ASV now skips
   OpenAlex when no contact email is configured and says so once, and the
   config page states the consequence on the field itself. At 50 citations the
   difference is a 12-minute resolution pass versus a 90-minute one.
6. **arXiv costs ~16 seconds per call** (`export.arxiv.org` paces requests
   hard) and a biomedical corpus is not on arXiv. Paying that on every citation
   is 13 minutes per run for zero yield, so arXiv and CORE now run only when
   every other resolver came up empty — which is the case they are actually for.

Also: **data.gov's CKAN API is gone.** `/api/3/action/*`, `/api/1/search` and
`/dataset.json` all answer 404 from something that is not CKAN any more. It is
off by default behind `ASV_ENABLE_DATA_GOV` rather than costing a round trip per
claim.

### Measured

15 citations from `hsv_cancer.pdf`, **no optional credentials set** (no
`UNPAYWALL_EMAIL`, so Unpaywall is skipped entirely; no CORE or TDM keys):

| | Old run (20260706_192057) | New, keyless |
|---|---|---|
| batches with exactly 1 candidate URL | 32/51 (63%) | 3/15 (20%) |
| batches with ≥2 candidates | 17/51 (33%) | 11/15 (73%) |
| bytes obtained | 16/51 (31%) | 8/15 (53%) |
| **judgeable full text** | not measured (the distinction did not exist) | 2/15 (13%) |

The headline number goes **down**, and that is the point: the old 31% counted
publisher landing pages as successes. Of the eight fetches that now succeed,
five are `abstract_only` and one is a `paywall_interstitial` — honestly graded
and honestly abstained on, per TIER0_PLAN.md §4. The 13% is the first number
this project has produced that means "we read the article".

One incidental find worth its own line: with `Referer`/`Sec-Fetch-*` in place,
`nature.com` returns **200** where it used to 403 — and the fetched 284KB was
being reduced to *zero characters* by the HTML extractor, because the junk-class
filter ran before the content root was chosen and Nature's wrapper carries the
layout class `eds-l-with-sidebar`. Choosing the root first, then cleaning inside
it, recovered 8.2k chars per Nature page.

### Not done

- **Phase 5** (`claude-in-chrome` operator rescue lane) — deliberately deferred;
  it is a human-in-the-loop workflow, not a pipeline change.
- **F9** citation-kind routing to `unresolvable_source_type`. The enum value
  (`unresolvable_by_design`) and the type list already exist and Tier 0.6 uses
  them for the reference audit, but the *acquisition* path does not yet skip
  book chapters.
- Persisting Playwright `storage_state()` across runs (F5's second half).
- Google Scholar is **off by default** (`ASV_ENABLE_SCHOLAR=1` to re-enable),
  per F4's "retire it or gate it behind an explicit opt-in flag". Gated rather
  than deleted because it remains the only route for a reference no index
  carries. Now that resolution runs as an up-front pass, leaving it on meant
  ~14 CAPTCHA-prone browser searches before the run could start.

---

## Appendix A — how the numbers were computed

```python
import json, glob, collections
from urllib.parse import urlparse

for path in glob.glob('runs/*/text_sources/_manifest.json'):
    ents = json.load(open(path))['entries']
    ok   = [e for e in ents if e.get('batch_download_successful')]
    errs = collections.Counter()
    for e in ents:
        for a in e.get('resolution_attempts') or []:
            if not a['downloaded']:
                errs[urlparse(a['url']).netloc] += 1
    print(path, len(ents), len(ok),
          collections.Counter(len(e['resolution_attempts']) for e in ents),
          errs.most_common(5))
```

Source files referenced throughout:
`src/asv/sourcefinder/academic_paper_finder.py`,
`src/asv/sourcefinder/text_downloader.py`,
`src/asv/sourcefinder/dataset_finder.py`,
`src/asv/sourcefinder/dataset_downloader.py`,
`src/asv/sourcefinder/browser_searcher.py`,
`src/asv/sourcefinder/config.py`,
`src/asv/orchestrator/claim_orchestrator.py` (`_setup_browser_searcher`,
`_bridge_browser_cookies`, `_process_cited_qualitative`).
