# ASV: Automated Source Validation

ASV audits the citations in an academic paper. It extracts the paper's factual claims,
finds the full text of the source each claim cites, and reports whether that source
actually supports the claim. When it can't check a claim, it says so and gives a reason
instead of guessing.

## Why

Across meta-analyses of the medical literature, 14.5–25.4% of quotations misrepresent
their source, and AI-assisted writing has added a new failure class: references that do
not exist. A claim can also be technically supported and still misleading: a murine
result cited as if it held for patients, a hedged correlation cited as a cause, a 2005
single-centre figure cited as a current national rate. Catching that "true but misleading"
class from the source text is where the project is headed
([`docs/VALUE_PROPOSITION.md`](docs/VALUE_PROPOSITION.md) §6).

## What it reports

Every claim gets one of five verdicts ([`src/asv/core/verdicts.py`](src/asv/core/verdicts.py)):

| Verdict | Meaning |
|---|---|
| `substantiated` | the cited source states or entails the claim |
| `partially_substantiated` | the source supports a weaker version (narrower population, hedged, different scope) |
| `not_substantiated` | full text was obtained and searched; it does not establish the claim |
| `contradicted` | the source says something incompatible |
| `not_checkable` | ASV declined to judge, always with a reason (`no_source_available`, `abstract_only`, `source_download_failed`, `retrieval_empty`, …) |

Two rules are enforced by the data model, not by convention:

- **No verdict without evidence.** The four judging verdicts need a quote that was found
  verbatim in the retrieved source, plus a resolvable source URL. If the model's quote
  can't be found, the verdict becomes `not_checkable(evidence_unverifiable)`.
- **No judging from model priors.** A claim with no citation, or whose source could only
  be fetched as an abstract, is never scored for plausibility.

Separately, every reference in the bibliography is checked against Crossref, OpenAlex,
Europe PMC, PubMed and DataCite to confirm that it exists and hasn't been retracted.

## Quick start

```bash
pip install -e ".[dev]"
cp .env.example .env            # set GEMINI_API_KEY and UNPAYWALL_EMAIL at minimum
python scripts/run_pipeline.py pdfs/<paper>.pdf
```

Each run writes everything to `runs/{pdf_stem}__{YYYYMMDD_HHMMSS}/`. To browse results,
compare runs and edit credentials in a web UI:

```bash
python scripts/run_webapp.py    # http://localhost:8000; credentials form at /config
```

[`docs/QUICKSTART.md`](docs/QUICKSTART.md) covers dev mode, output formats,
configuration and troubleshooting.

## How it works

```
PDF ─► Stage 1  extraction    claims + citations (Gemini, chunked)
    ─► Step 0   bibliography audit: does each reference exist? is it retracted?
    ─► Step 0b  resolve every cited source to ranked full-text candidates
    ─► Stage 2  orchestration, four groups in order:
         qualitative uncited    → not_checkable(no_source_available), no model call
         quantitative uncited   → dataset search; if found, treated as cited
         qualitative cited      ┐ batched per citation: download once, content-quality
         quantitative cited     ┘ gate, TF-IDF retrieval, LLM judgment, quote check
                                  (dataset-backed quant: LLM-written pandas script)
    ─► validation_results/*.json, manifests, run_summary.json
```

Source acquisition queries every resolver it knows (Europe PMC, the PMC ID converter,
NCBI efetch, OpenAlex, Unpaywall, Semantic Scholar, Crossref, CORE, arXiv, and publisher
text-mining APIs when keys are set), ranks the candidates (structured full text first,
landing pages last), and falls back to a logged-in browser and an optional library
EZproxy for paywalled hosts. Every fetch goes through one rate-limited, retrying,
caching HTTP layer.

## Where it stands

On the reference paper (`hsv_cancer.pdf`, 306 claims, 253 references) the honest
headline is still small: most claims are `not_checkable`, mostly because claims lose
their citations during extraction and because cited sources come back as abstracts.
There is no labelled gold set yet, so there is no measured precision or false-accusation
rate. [`docs/README.md`](docs/README.md) tracks the plan and what's done.

**Security:** the dataset-backed path runs LLM-generated Python unsandboxed, with the
pipeline's environment (including API keys). Don't run ASV on untrusted PDFs.

## Repository layout

```
src/asv/
  core/          models, verdict ontology, run folders, credentials catalogue, LLM routing
  extraction/    Stage 1: claim + citation extraction
  orchestrator/  Stage 2: routing and batch processing
  validator/     RAG verification, quote verification, script validator
  sourcefinder/  resolution, downloading, content-quality gate, bibliography audit
  benchmark/     gold-set schema and metrics
apps/
  api/           FastAPI service
  web/           React + Vite frontend
scripts/         CLI entry points, audit and benchmark tools (see scripts/README.md)
docs/            plans, analyses and guides (see docs/README.md)
```

## Documentation

- [`CLAUDE.md`](CLAUDE.md): the most complete technical reference (architecture, config, invariants)
- [`docs/README.md`](docs/README.md): index of plans and analyses, with status
- Module READMEs: [extraction](src/asv/extraction/README.md) ·
  [orchestrator](src/asv/orchestrator/README.md) ·
  [validator](src/asv/validator/README.md) ·
  [sourcefinder](src/asv/sourcefinder/README.md)

## License

Not yet specified.
