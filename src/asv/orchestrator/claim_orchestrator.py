"""Claim Orchestrator - Main orchestration pipeline for claim validation"""

import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from collections import defaultdict

from asv.core.models import (
    ClaimObject, ValidationResult, ValidationBatch, CitationDetails,
    ReferenceCheck, ResolutionAttempt, SourceManifestEntry,
    RESULT_SCHEMA_VERSION, not_checkable,
)
from asv.core.verdicts import (
    ContentQuality, NotCheckableReason, ReferenceStatus, RetractionStatus, Verdict,
    CONTENT_QUALITY_REASON,
)
from asv.extraction.llm_client import LLMClient
from asv.core.run_paths import RunPaths
from asv.core.run_events import RunEventLogger
from asv.core.interaction import InteractionHandler, ConsoleInteractionHandler
from asv.sourcefinder import DatasetFinder, TextFinder, DatasetDownloader, TextDownloader
from asv.sourcefinder.browser_searcher import BrowserSearcher
from asv.sourcefinder import polite_http
from asv.sourcefinder.config import ENABLE_REFERENCE_CHECK, KNOWN_PAYWALL_DOMAINS
from asv.sourcefinder.reference_verifier import ReferenceVerifier
from asv.sourcefinder.source_manifest import SourceManifest
from asv.validator.llm_verifier import LLMVerifier
from .process_quantitative import ProcessQuantitative
from .process_qualitative import ProcessQualitative

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# B4: opt-in retention of downloaded dataset/text-source files. Off by
# default — the pipeline deletes them post-batch to conserve disk (see
# CLAUDE.md). Set ASV_KEEP_SOURCES=1 to keep them so the web UI's claim-detail
# view (S4) can show the actual retrieved source instead of just its manifest.
_KEEP_SOURCES = os.getenv("ASV_KEEP_SOURCES", "").strip().lower() in ("1", "true", "yes")


def _setup_file_logging(log_path: Path) -> Path:
    """Add a file handler writing to ``log_path`` to the root logger."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    logging.getLogger().addHandler(file_handler)
    return log_path


class ClaimOrchestrator:
    """Main orchestrator for claim validation"""

    def __init__(self, run_paths: RunPaths, interaction: Optional[InteractionHandler] = None):
        self.run_paths = run_paths
        self.output_dir = run_paths.validation_results

        self._log_path = _setup_file_logging(run_paths.orchestration_log())
        logger.info(f"Orchestrator initialised. Run folder: {run_paths.root}")
        logger.info(f"Log file: {self._log_path}")

        # Machine-readable progress channel (logs/events.jsonl) — always on,
        # for both CLI and API-driven runs. See run_events.py / B1.
        self.events = RunEventLogger(run_paths)

        # Paywall-login checkpoint. Defaults to the CLI's original print+input
        # behavior; the web backend injects FileInteractionHandler instead.
        self.interaction: InteractionHandler = interaction or ConsoleInteractionHandler()

        # Initialize LLM client
        self.llm_client = LLMClient()

        # Initialize tool validators
        self.llm_verifier = LLMVerifier(self.llm_client)

        # Initialize process orchestrators
        self.quant_processor = ProcessQuantitative(self.llm_client, run_paths=run_paths)
        self.qual_processor = ProcessQualitative(self.llm_client)

        # Initialize sourcefinder tools
        self.dataset_finder = DatasetFinder(llm_client=self.llm_client, run_paths=run_paths)
        self.text_finder = TextFinder(llm_client=self.llm_client, run_paths=run_paths)
        self.dataset_downloader = DatasetDownloader(run_paths=run_paths)
        self.text_downloader = TextDownloader(run_paths=run_paths, llm_client=self.llm_client)

        # Persistent per-folder manifests — survive batch cleanup so a run
        # remains auditable after datasets/text_sources files are deleted.
        self.dataset_manifest = SourceManifest(
            run_paths.datasets_manifest_json(), run_paths.pdf_stem
        )
        self.text_source_manifest = SourceManifest(
            run_paths.text_sources_manifest_json(), run_paths.pdf_stem
        )

        # Tier 0.6 — bibliography audit. Reuses the paper finder's LLM citation
        # parser, which is already called (and cached) once per citation string
        # during resolution, so the audit adds no LLM cost.
        self.reference_verifier = ReferenceVerifier(
            parse_citation=self.text_downloader._paper_finder._parse_citation_with_llm,
        )
        self.reference_checks: Dict[str, ReferenceCheck] = {}

        # Citations dict populated when claims are loaded from JSON
        self.citations_dict: Dict[str, str] = {}

        # Browser searcher — created lazily in _setup_browser_searcher()
        self.browser_searcher: BrowserSearcher = None

    def process_claims(
        self, claims: List[ClaimObject], citations: Dict[str, str] = None
    ) -> Dict[str, Any]:
        """
        Main processing pipeline following the specified order.
        Returns validation results grouped by claim type.

        Args:
            claims: sorted list of ClaimObject from the extractor
            citations: dict mapping citation_id -> full bibliography text,
                       used for open-access resolution of cited sources
        """
        if citations:
            self.citations_dict = citations

        self._start_browser()

        run_start = time.time()
        logger.info(f"\n{'='*60}")
        logger.info(f"Starting validation of {len(claims)} claims")
        logger.info(f"{'='*60}\n")
        self.events.emit("run_started", total_claims=len(claims))

        # Step 0: bibliography audit (Tier 0.6). Runs before anything else
        # because a reference that cannot be found in any index changes what
        # every claim citing it can possibly mean — and because a verified
        # reference hands the resolver a DOI it would otherwise only discover
        # as a last resort.
        t0 = time.time()
        self._audit_references(claims, self.citations_dict)
        step_timings_reference = round(time.time() - t0, 2)

        # Step 0b: resolve every cited source to candidate URLs *before* any
        # claim is processed. Two things fall out of this ordering, both from
        # SOURCE_ACQUISITION.md F6:
        #   1. The paywall-login checkpoint can name the publishers that
        #      actually came back, instead of grepping bibliography text for
        #      domain names that were never in it. The measured run logged
        #      "no known paywall domains detected" and then 403'd 41 times.
        #   2. Resolution is cached, so the per-batch calls that follow are
        #      cache hits — this is a reordering, not extra work.
        t0 = time.time()
        self._resolution_prepass(claims)
        step_timings_resolution = round(time.time() - t0, 2)
        self._paywall_login_checkpoint()

        results = {
            "qualitative_uncited": [],
            "quantitative_uncited": [],
            "qualitative_cited": [],
            "quantitative_cited": []
        }
        step_timings: Dict[str, float] = {
            "reference_audit": step_timings_reference,
            "source_resolution": step_timings_resolution,
        }

        # Step 1: Qualitative without citation
        logger.info("Step 1: Processing qualitative claims without citations...")
        qual_uncited = [c for c in claims if c.claim_type == "qualitative" and not c.citation_id]
        self.events.emit("step_started", step="qualitative_uncited", count=len(qual_uncited))
        t0 = time.time()
        results["qualitative_uncited"] = self._process_uncited_qualitative(qual_uncited)
        step_timings["qualitative_uncited"] = round(time.time() - t0, 2)
        self.events.emit("step_finished", step="qualitative_uncited", elapsed_seconds=step_timings["qualitative_uncited"])

        # Step 2: Quantitative without citation.
        # Splits into (a) claims with a dataset source found — routed to Step 4, and
        # (b) terminal direct_results (truth-table/LLM verified OR no source found) —
        # written directly to quantitative_uncited_results.json.
        logger.info("\nStep 2: Processing quantitative claims without citations...")
        quant_uncited = [c for c in claims if c.claim_type == "quantitative" and not c.citation_id]
        self.events.emit("step_started", step="quantitative_uncited", count=len(quant_uncited))
        t0 = time.time()
        quant_with_found_sources, quant_uncited_direct_results = \
            self._process_uncited_quantitative(quant_uncited)
        results["quantitative_uncited"] = quant_uncited_direct_results
        step_timings["quantitative_uncited"] = round(time.time() - t0, 2)
        self.events.emit("step_finished", step="quantitative_uncited", elapsed_seconds=step_timings["quantitative_uncited"])

        # Step 3: Qualitative with citation (matches README ordering: qual cited before quant cited)
        logger.info("\nStep 3: Processing qualitative claims with citations...")
        qual_cited = [c for c in claims if c.claim_type == "qualitative" and c.citation_id]
        self.events.emit("step_started", step="qualitative_cited", count=len(qual_cited))
        t0 = time.time()
        results["qualitative_cited"] = self._process_cited_qualitative(qual_cited)
        step_timings["qualitative_cited"] = round(time.time() - t0, 2)
        self.events.emit("step_finished", step="qualitative_cited", elapsed_seconds=step_timings["qualitative_cited"])

        # Step 4: Combine originally-uncited-now-cited + originally-cited quantitative.
        # quant_with_found_sources already only contains claims that resolved a dataset.
        logger.info("\nStep 4: Processing quantitative claims with citations...")
        quant_cited = [c for c in claims if c.claim_type == "quantitative" and c.citation_id]
        all_quant_cited = quant_with_found_sources + quant_cited
        self.events.emit("step_started", step="quantitative_cited", count=len(all_quant_cited))
        t0 = time.time()
        results["quantitative_cited"] = self._process_cited_quantitative(all_quant_cited)
        step_timings["quantitative_cited"] = round(time.time() - t0, 2)
        self.events.emit("step_finished", step="quantitative_cited", elapsed_seconds=step_timings["quantitative_cited"])

        # Save results and summary
        self._save_results(results)
        self._save_run_summary(claims, results, step_timings, run_start)

        # Persist sourcefinder discovery records (in-memory across run)
        dataset_records_path = self.dataset_finder.save_discovery_records()
        if dataset_records_path is not None:
            logger.info(f"✓ Dataset discovery records saved to: {dataset_records_path}")
        text_records_path = self.text_finder.save_discovery_records()
        if text_records_path is not None:
            logger.info(f"✓ Text source discovery records saved to: {text_records_path}")

        # Clean up browser if it was started
        if self.browser_searcher is not None:
            self.browser_searcher.close()
            self.browser_searcher = None

        total_elapsed = round(time.time() - run_start, 2)
        logger.info(f"\n{'='*60}")
        logger.info(f"Validation complete! Total time: {total_elapsed}s")
        logger.info(f"Log file: {self._log_path}")
        logger.info(f"{'='*60}\n")
        self.events.emit("run_finished", total_elapsed_seconds=total_elapsed)

        return results

    def _start_browser(self) -> None:
        """Create the BrowserSearcher and inject it into every finder.

        Lazy: ``BrowserSearcher`` does not launch Chromium until something asks
        it to, so this costs nothing for a run that never needs a browser. The
        login checkpoint is a separate step (``_paywall_login_checkpoint``)
        because it cannot run until resolution has told us which publishers are
        actually involved.
        """
        self.browser_searcher = BrowserSearcher(llm_client=self.llm_client)
        self.dataset_finder.browser_searcher = self.browser_searcher
        self.text_finder.browser_searcher = self.browser_searcher
        self.text_downloader._paper_finder.browser_searcher = self.browser_searcher

    def _resolution_prepass(self, claims: List[ClaimObject]) -> None:
        """Resolve every distinct cited source to candidate URLs, up front.

        The resolver caches per citation string, so the batches later in the run
        read this back instead of re-resolving. What the pass buys is knowledge
        we do not otherwise have until it is too late to act on: the set of
        hosts the paper's bibliography actually points at.
        """
        citation_ids: Dict[str, Optional[str]] = {}
        for claim in claims:
            cid = str(claim.citation_id or "")
            if not cid or claim.found_source is not None or cid in citation_ids:
                continue
            raw = self.citations_dict.get(cid)
            if not raw:
                continue
            citation_ids[cid] = (
                claim.citation_details.doi if claim.citation_details else None
            )

        if not citation_ids:
            logger.info("No cited sources to resolve — skipping resolution pass")
            return

        total = len(citation_ids)
        logger.info(f"\nStep 0b: Resolving {total} cited sources to candidate URLs...")
        self.events.emit("step_started", step="source_resolution", count=total)

        finder = self.text_downloader._paper_finder
        with_candidates = 0
        for i, (cid, doi) in enumerate(citation_ids.items(), 1):
            try:
                candidates = finder.find_candidates(
                    self.citations_dict.get(cid, ""), known_doi=doi
                )
            except Exception as e:
                logger.warning(f"  Resolution failed for [{cid}]: {e}")
                continue
            if candidates:
                with_candidates += 1
            if i % 10 == 0 or i == total:
                logger.info(f"  Resolution: {i}/{total} ({with_candidates} with candidates)")

        logger.info(
            f"  Resolution pass complete: {with_candidates}/{total} citations have "
            f"at least one candidate URL across {len(finder.resolved_hosts)} host(s)"
        )
        self.events.emit(
            "step_finished", step="source_resolution",
            citations=total, with_candidates=with_candidates,
            hosts=len(finder.resolved_hosts),
        )

    def _paywall_login_checkpoint(self) -> None:
        """Prompt for manual login, using the hosts resolution actually produced.

        The old trigger substring-matched ``KNOWN_PAYWALL_DOMAINS`` against raw
        bibliography text. Bibliography entries contain journal names, not URLs,
        so it essentially never fired: the measured run logged *"No known
        paywall domains detected in citations"* and then returned 403 forty-one
        times from wiley.com, cell.com, oup.com and asm.org (F6).
        """
        if self.browser_searcher is None:
            return
        resolved = self.text_downloader._paper_finder.resolved_hosts
        paywall_domains_needed = sorted({
            domain for domain in KNOWN_PAYWALL_DOMAINS
            for host in resolved
            if host == domain or host.endswith("." + domain)
        })

        if not paywall_domains_needed:
            logger.info(
                "No known paywall domains among the resolved source hosts — "
                "browser ready (no login needed)"
            )
            return

        logger.info(
            f"Paywall domains among resolved sources: {paywall_domains_needed}\n"
            "Opening browser tabs for manual login..."
        )
        try:
            self.browser_searcher.open_domains(paywall_domains_needed)
        except Exception as e:
            # This step runs after the audit and the resolution pass — half an
            # hour of work on a real corpus. A browser that will not launch
            # (Playwright not installed, no display, a version mismatch) must
            # cost us the login, not the run. Everything downstream already
            # treats an unauthenticated fetch as the normal case.
            logger.warning(
                f"Could not open browser tabs for login ({e}) — continuing "
                f"without institutional access. Publisher fetches will be "
                f"unauthenticated."
            )
            self.browser_searcher = None
            self.text_downloader._paper_finder.browser_searcher = None
            self.dataset_finder.browser_searcher = None
            self.text_finder.browser_searcher = None
            return
        # Replaces the pipeline's original bare print()/input() — the default
        # ConsoleInteractionHandler behaves identically for the CLI; the web
        # backend injects FileInteractionHandler instead (see interaction.py, B6).
        self.interaction.await_login(paywall_domains_needed)

        # Bridge the just-authenticated Playwright cookies into every downstream
        # HTTP client. Without this, the manual login would live only in the
        # browser context — but almost all fetches happen through
        # ``requests.Session`` objects that don't share cookies with Playwright.
        # After this step, ``TextDownloader.download``,
        # ``AcademicPaperFinder._session`` (OA API calls + fetch_with_cookies),
        # and ``DatasetDownloader.download`` all send the user's session cookies
        # transparently.
        self._bridge_browser_cookies()

    def _bridge_browser_cookies(self) -> None:
        """
        Harvest cookies from the authenticated Playwright browser context and
        inject them into every ``requests.Session`` the pipeline uses, plus the
        ``AcademicPaperFinder._inst_cookies`` dict so ``fetch_with_cookies`` can
        find them by domain.

        Called by ``_setup_browser_searcher`` immediately after the user
        presses Enter to signal login completion.
        """
        if self.browser_searcher is None:
            return
        cookies = self.browser_searcher.export_cookies()
        if not cookies:
            logger.info("Browser context has no cookies to bridge — skipping")
            return

        sessions = [
            self.text_downloader.session,
            self.text_downloader._paper_finder._session,
            self.dataset_downloader.session,
        ]
        applied = 0
        for c in cookies:
            name = c.get("name")
            value = c.get("value")
            if not name or value is None:
                continue
            domain = c.get("domain", "")
            path = c.get("path", "/")
            for session in sessions:
                try:
                    session.cookies.set(name, value, domain=domain, path=path)
                except Exception:
                    # requests can reject cookies with unusual attributes
                    # (SameSite=None + no Secure, exotic paths). Skip silently
                    # so one bad cookie doesn't break the whole bridge.
                    continue
            applied += 1

        # Also merge into the AcademicPaperFinder's domain-keyed
        # institutional-cookies dict so fetch_with_cookies() looks them up by
        # netloc — Playwright's domain strings sometimes include a leading dot,
        # but urlparse().netloc never does, so normalize.
        inst = self.text_downloader._paper_finder._inst_cookies
        for c in cookies:
            name = c.get("name")
            value = c.get("value")
            domain = c.get("domain", "").lstrip(".")
            if not name or value is None or not domain:
                continue
            inst.setdefault(domain, {})[name] = value

        touched_domains = sorted({c.get("domain", "").lstrip(".") for c in cookies if c.get("domain")})
        logger.info(
            f"Bridged {applied} browser cookies into {len(sessions)} requests sessions "
            f"and paper-finder inst_cookies (domains: {touched_domains})"
        )

        # Our credentials just changed, so nothing cached before this point
        # describes what we would get now. Without this the resolution pass's
        # pre-login 403s would be served straight back from disk and the manual
        # login would silently accomplish nothing.
        polite_http.bump_auth_generation()

    # ------------------------------------------------------------------
    # Stage 0 — bibliography audit (Tier 0.6)
    # ------------------------------------------------------------------

    def _audit_references(
        self, claims: List[ClaimObject], citations: Dict[str, str]
    ) -> None:
        """Check every reference for existence and retraction, then feed the
        recovered DOIs forward into source resolution.

        Runs over the *whole* bibliography, not just the references with claims
        attached: a complete reference audit is itself a deliverable, and it
        costs only HTTP calls against keyless indexes.
        """
        if not ENABLE_REFERENCE_CHECK:
            logger.info("Reference audit disabled (ASV_REFERENCE_CHECK=0) — skipping")
            return
        if not citations:
            logger.info("No bibliography entries to audit — skipping reference check")
            return

        logger.info(f"\nStep 0: Auditing {len(citations)} bibliography references...")
        self.events.emit("step_started", step="reference_audit", count=len(citations))

        def _progress(i: int, total: int, check: ReferenceCheck) -> None:
            if i % 25 == 0 or i == total:
                logger.info(f"  Reference audit: {i}/{total}")

        self.reference_checks = self.reference_verifier.verify_all(citations, _progress)

        counts: Dict[str, int] = defaultdict(int)
        for check in self.reference_checks.values():
            counts[check.status.value] += 1
            if check.retraction_status == RetractionStatus.RETRACTED:
                counts["retracted"] += 1
            elif check.retraction_status == RetractionStatus.CONCERN_RAISED:
                counts["concern_raised"] += 1

        logger.info(
            "  Reference audit complete: "
            + ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
        )
        for cid, check in self.reference_checks.items():
            if check.status == ReferenceStatus.NOT_FOUND_IN_INDEXES:
                logger.warning(f"  ⚠ Reference [{cid}] {check.explanation}")
            if check.retraction_status == RetractionStatus.RETRACTED:
                logger.warning(f"  ⚠ Reference [{cid}] is RETRACTED: {check.matched_title}")

        self._save_reference_checks(counts)
        self.events.emit("step_finished", step="reference_audit", **dict(counts))

        # Feed verified DOIs forward. SOURCE_ACQUISITION.md measures that 32 of
        # 51 batches have exactly one candidate URL, and the resolver only
        # reaches Crossref DOI recovery after everything else fails. On a corpus
        # where zero of 253 references carry an inline DOI, handing the resolver
        # a DOI up front is the cheapest acquisition improvement available.
        enriched = 0
        for claim in claims:
            check = self.reference_checks.get(str(claim.citation_id or ""))
            if check is None or not check.matched_doi:
                continue
            existing = claim.citation_details
            if existing is not None and existing.doi:
                continue
            claim.citation_details = CitationDetails(
                title=(existing.title if existing else None) or check.matched_title,
                authors=existing.authors if existing else None,
                year=existing.year if existing else None,
                url=existing.url if existing else None,
                doi=check.matched_doi,
                raw_text=(existing.raw_text if existing else None)
                or check.raw_citation_text,
            )
            enriched += 1
        if enriched:
            logger.info(f"  ✓ Attached verified DOIs to {enriched} claims for resolution")

    def _save_reference_checks(self, counts: Dict[str, int]) -> None:
        path = self.run_paths.reference_checks_json()
        payload = {
            "pdf_stem": self.run_paths.pdf_stem,
            "generated_at": datetime.now().isoformat(),
            "summary": dict(counts),
            "checks": [c.model_dump(mode="json") for c in self.reference_checks.values()],
        }
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            logger.info(f"  ✓ Reference audit saved to: {path}")
        except Exception as e:
            logger.error(f"  Failed to write reference audit: {e}")

    def _reference_flags(self, citation_id: Optional[str]) -> List[str]:
        """Orthogonal signals from the bibliography audit.

        Deliberately *flags*, not verdicts: a retracted source can still contain
        the sentence being cited, and a reference that no index carries says
        nothing about whether the claim is true.
        """
        check = self.reference_checks.get(str(citation_id or ""))
        if check is None:
            return []
        flags = []
        if check.retraction_status == RetractionStatus.RETRACTED:
            flags.append("cited_source_retracted")
        elif check.retraction_status == RetractionStatus.CONCERN_RAISED:
            flags.append("cited_source_concern_raised")
        if check.status in (
            ReferenceStatus.NOT_FOUND_IN_INDEXES, ReferenceStatus.UNINDEXED_BY_DESIGN
        ):
            flags.append("reference_unindexed")
        return flags

    # ------------------------------------------------------------------
    # Shared batch helpers
    # ------------------------------------------------------------------

    def _batch_outcome(
        self, download_result: Dict[str, Any]
    ) -> Tuple[bool, Optional[ContentQuality], Optional[NotCheckableReason], str]:
        """Classify a batch's source into the three-way outcome of Tier 0.3.

        Returns ``(judgeable, content_quality, abstention_reason, note)``.

        The middle case — bytes arrived but they are an abstract or an access
        wall — is the one the pre-Tier-0 pipeline had no way to express. Ten of
        sixteen successful downloads in the measured run were publisher landing
        pages carrying an abstract and a reference list; RAG then searched a
        document that could not contain the evidence, and whatever came back was
        reported as a verdict about the claim.
        """
        quality = download_result.get('content_quality')
        if isinstance(quality, str):
            quality = ContentQuality(quality)

        if not download_result.get('downloaded'):
            error = download_result.get('error') or "no candidate URL could be fetched"
            reason = (
                NotCheckableReason.SOURCE_NOT_RESOLVED
                if not download_result.get('attempts')
                else NotCheckableReason.SOURCE_DOWNLOAD_FAILED
            )
            return False, quality, reason, f"Source could not be obtained: {error}"

        if download_result.get('judgeable'):
            return True, quality, None, "Full text obtained"

        reason = CONTENT_QUALITY_REASON.get(
            quality, NotCheckableReason.CONTENT_REJECTED
        )
        signals = download_result.get('content_signals') or {}
        note = (
            f"Source obtained but not usable as evidence "
            f"({quality.value if quality else 'unknown'}): "
            f"{signals.get('usable_chars', '?')} chars, "
            f"{signals.get('imrad_count', 0)} IMRaD section(s)"
        )
        return False, quality, reason, note

    def _abstain_batch(
        self,
        citation_id: str,
        first_claim: ClaimObject,
        claims_group: List[ClaimObject],
        reason: NotCheckableReason,
        note: str,
        *,
        attempts: List[ResolutionAttempt],
        download_result: Dict[str, Any],
        method: str,
        quality: Optional[ContentQuality],
    ) -> ValidationBatch:
        """Build a batch where no claim could be judged, with an honest reason."""
        explanation = {
            NotCheckableReason.SOURCE_NOT_RESOLVED:
                "No URL could be resolved for the cited source, so this claim could "
                "not be checked.",
            NotCheckableReason.SOURCE_DOWNLOAD_FAILED:
                "The cited source could not be downloaded, so this claim could not be "
                "checked. This says nothing about whether the claim is correct.",
            NotCheckableReason.ABSTRACT_ONLY:
                "Only an abstract or landing page could be obtained for the cited "
                "source. ASV does not judge a claim against an abstract — the "
                "evidence for most claims lives in the full text.",
            NotCheckableReason.PAYWALL_INTERSTITIAL:
                "The cited source returned an access wall rather than the article, so "
                "this claim could not be checked.",
            NotCheckableReason.CONTENT_REJECTED:
                "The cited source returned no usable text, so this claim could not be "
                "checked.",
        }.get(reason, note)

        winning_url = download_result.get('winning_url')
        flags = self._reference_flags(citation_id)
        claim_results = [
            not_checkable(
                claim, reason, explanation,
                method=method,
                errors=download_result.get('error'),
                flags=list(flags),
                source_url=winning_url,
                content_quality=quality,
            )
            for claim in claims_group
        ]

        for claim in claims_group:
            self.events.emit(
                "claim_validated", claim_id=claim.claim_id,
                verdict=Verdict.NOT_CHECKABLE.value, reason=reason.value,
            )

        return ValidationBatch(
            citation_id=citation_id,
            citation_text=first_claim.citation_text,
            download_successful=bool(download_result.get('downloaded')),
            judgeable=False,
            content_quality=quality,
            source_path=download_result.get('path'),
            source_url=winning_url,
            resolution_attempts=attempts,
            reference_check=self.reference_checks.get(str(citation_id)),
            claim_results=claim_results,
            batch_notes=note,
        )

    # ------------------------------------------------------------------
    # Uncited claims (Tier 0.1)
    # ------------------------------------------------------------------

    def _process_uncited_qualitative(self, claims: List[ClaimObject]) -> List[ValidationResult]:
        """Uncited qualitative claims are not checkable. Full stop.

        Tier 0.1. This method used to ask the Google Fact Check API and then a
        small LLM whether the sentence sounded plausible, and report the answer
        as a verdict with a confidence score. On the measured corpus that
        produced 207 "passes" out of 233 claims with ``sources_used: []`` —
        81% of all output and 97% of all passes, none of it backed by anything.

        Worse, it inverted the project's own thesis twice over: it manufactured
        exactly the confident-looking unsupported number ASV exists to catch,
        and because a genuinely novel finding is by definition absent from a
        model's priors, it scored *originality* lowest and platitudes highest.

        There is no LLM call here any more.
        """
        results = []

        for claim in claims:
            reason = (
                NotCheckableReason.ORIGINAL_CONTRIBUTION if claim.is_original
                else NotCheckableReason.NO_SOURCE_AVAILABLE
            )
            explanation = (
                "The paper presents this as its own contribution, so there is no external "
                "source to check it against. (ASV does not assess whether a novel finding "
                "is correct — only whether cited sources support what is claimed of them.)"
                if claim.is_original else
                "No citation was attached to this claim in the source document, so there "
                "is no source to check it against. ASV does not judge claims from model "
                "priors."
            )
            results.append(not_checkable(claim, reason, explanation))
            self.events.emit(
                "claim_validated", claim_id=claim.claim_id,
                verdict=Verdict.NOT_CHECKABLE.value, reason=reason.value,
            )

        logger.info(
            f"  {len(results)} uncited qualitative claims recorded as not checkable "
            f"(no LLM calls made)"
        )
        return results

    def _process_uncited_quantitative(
        self, claims: List[ClaimObject]
    ) -> Tuple[List[ClaimObject], List[ValidationResult]]:
        """
        Process quantitative claims without citations.
        - Truth Table + LLM Check
        - If not sufficiently answered, use sourcefinder

        Returns:
          - claims_to_route: only claims where a dataset source was found —
            these proceed to Step 4 batch validation with citation_id="found_{claim_id}".
          - direct_results: abstentions for claims where no dataset could be
            located. These land directly in quantitative_uncited_results.json.

        Tier 0.1 removed the plausibility short-circuit that used to sit in
        front of the dataset search. It did not merely report a verdict from
        priors — it *gated acquisition on one*, skipping the source search
        entirely whenever a small model said the sentence sounded right above
        0.8. That is the worst instance of the pattern in the codebase: the
        less a claim looked like it needed checking, the less it got checked.
        Every uncited quantitative claim now attempts source resolution.
        """
        claims_to_route: List[ClaimObject] = []
        direct_results: List[ValidationResult] = []

        for claim in claims:
            logger.info(f"  Processing: {claim.claim_id}")
            logger.info("    Searching for dataset...")
            found_source = self.dataset_finder.find_dataset(claim.text, claim.claim_id)

            if found_source:
                claim.originally_uncited = True
                claim.found_source = found_source
                claim.citation_found = True
                claim.citation_id = f"found_{claim.claim_id}"
                claim.citation_text = f"[Found: {found_source.source_type}]"
                claim.citation_details = CitationDetails(
                    title=f"Dataset from {found_source.source_type}",
                    authors=None,
                    year=None,
                    url=found_source.source_url,
                    doi=None,
                    raw_text=f"Found dataset: {found_source.source_url}"
                )
                logger.info(f"    ✓ Found dataset: {found_source.source_url}")
                claims_to_route.append(claim)
            else:
                logger.warning("    ✗ No dataset found for claim")
                # Previously reported as passed=False, confidence 0.0 — which
                # reads as "this claim is wrong" when it means "we never checked
                # it". Same correction as the batch-download-failure path.
                direct_results.append(not_checkable(
                    claim,
                    NotCheckableReason.SOURCE_NOT_RESOLVED,
                    "This quantitative claim carries no citation, and no dataset "
                    "matching it could be located, so there is nothing to check it "
                    "against.",
                    method="source_not_found",
                ))
                self.events.emit(
                    "claim_validated", claim_id=claim.claim_id,
                    verdict=Verdict.NOT_CHECKABLE.value,
                    reason=NotCheckableReason.SOURCE_NOT_RESOLVED.value,
                )

        return claims_to_route, direct_results

    def _process_cited_quantitative(self, claims: List[ClaimObject]) -> List[ValidationBatch]:
        """
        Route cited-quantitative claims by source shape.

        A claim's ``found_source`` is set only when ``_process_uncited_quantitative``
        located a real dataset via ``DatasetFinder`` (data.gov, Kaggle, Zenodo, etc.).
        Those claims carry a genuine tabular URL and go through the strict
        ``DatasetDownloader → PythonScriptValidator`` path.

        Every other cited-quant claim carries a citation to an *academic paper*.
        Papers rarely publish raw data at the citation URL — the numbers live in
        the prose. Route those through the text-source pipeline (same as the
        cited-qualitative flow) so a paper's PDF/HTML can be RAG-searched by the
        LLM verifier.
        """
        dataset_backed = [c for c in claims if c.found_source is not None]
        paper_backed = [c for c in claims if c.found_source is None]

        logger.info(
            f"  Routing quant-cited claims: "
            f"{len(dataset_backed)} dataset-backed, {len(paper_backed)} paper-backed"
        )

        results: List[ValidationBatch] = []
        if dataset_backed:
            results.extend(self._process_dataset_backed_quant(dataset_backed))
        if paper_backed:
            results.extend(self._process_paper_backed_quant(paper_backed))
        return results

    def _process_dataset_backed_quant(
        self, claims: List[ClaimObject]
    ) -> List[ValidationBatch]:
        """Strict dataset flow: download tabular data, run generated Python script."""
        batches = defaultdict(list)
        for claim in claims:
            batches[claim.citation_id].append(claim)

        batch_results = []

        for citation_id, claims_group in batches.items():
            logger.info(f"  [dataset] Batch [{citation_id}]: {len(claims_group)} claims")
            self.events.emit(
                "batch_started", step="quantitative_cited",
                citation_id=str(citation_id), num_claims=len(claims_group),
            )
            first_claim = claims_group[0]

            # Resolve URL: use known URL → open-access candidates → iterate on 4xx.
            # Each candidate is tagged with its resolution phase so the manifest
            # can preserve the full cascade after the batch cleans up.
            candidates: list[tuple[str, str]] = []  # (url, source_label)
            if first_claim.citation_details and first_claim.citation_details.url:
                # Uncited-quant claims that resolved to a dataset arrive here with
                # citation_details.url populated from FoundDatasetSource — tag
                # accordingly so the manifest can distinguish them.
                label = 'found_dataset' if first_claim.found_source else 'direct'
                candidates.append((first_claim.citation_details.url, label))
            raw_citation_text = self.citations_dict.get(str(citation_id), "")
            if raw_citation_text:
                known_doi = (
                    first_claim.citation_details.doi if first_claim.citation_details else None
                )
                for u in self.text_downloader._paper_finder.find_urls(
                    raw_citation_text, known_doi=known_doi
                ):
                    if u not in [c[0] for c in candidates]:
                        candidates.append((u, 'open_access'))

            attempts: list[ResolutionAttempt] = []
            download_result = {'downloaded': False, 'error': 'No URL found via open-access APIs'}
            winning_url: str | None = None
            for i, (url, source_label) in enumerate(candidates, 1):
                logger.info(f"    Attempt {i}/{len(candidates)}: {url}")
                download_result = self.dataset_downloader.download(url, citation_id)
                attempts.append(ResolutionAttempt(
                    url=url,
                    source=source_label,
                    downloaded=bool(download_result.get('downloaded')),
                    error=download_result.get('error'),
                ))
                self.events.emit(
                    "resolution_attempt", citation_id=str(citation_id), url=url,
                    source=source_label, downloaded=bool(download_result.get('downloaded')),
                )
                if download_result['downloaded']:
                    winning_url = url
                    break

            downloaded_at = datetime.now().isoformat() if download_result.get('downloaded') else None
            manifest_entry = SourceManifestEntry(
                citation_id=str(citation_id),
                citation_text=first_claim.citation_text,
                raw_citation_text=raw_citation_text or None,
                citation_details=first_claim.citation_details,
                resolution_attempts=attempts,
                winning_url=winning_url,
                format=download_result.get('format'),
                filename=Path(download_result['path']).name if download_result.get('path') else None,
                downloaded_at=downloaded_at,
                batch_num_claims=len(claims_group),
                batch_download_successful=bool(download_result.get('downloaded')),
                batch_judgeable=bool(download_result.get('downloaded')),
                found_source=first_claim.found_source,
            )
            self.dataset_manifest.append(manifest_entry)

            if not download_result['downloaded']:
                logger.error(f"    ✗ Download failed: {download_result.get('error')}")
                reason = (
                    NotCheckableReason.SOURCE_NOT_RESOLVED if not attempts
                    else NotCheckableReason.SOURCE_DOWNLOAD_FAILED
                )
                batch_results.append(self._abstain_batch(
                    citation_id, first_claim, claims_group, reason,
                    f"Source could not be obtained: {download_result.get('error')}",
                    attempts=attempts,
                    download_result={**download_result, 'winning_url': None},
                    method="python_script",
                    quality=None,
                ))
                self.events.emit(
                    "batch_finished", citation_id=str(citation_id), download_successful=False,
                    num_claims=len(claims_group),
                )
                continue

            logger.info(f"    ✓ Downloaded dataset: {download_result['path']}")

            claim_results = []
            for claim in claims_group:
                logger.info(f"      Validating: {claim.claim_id}")
                result = self.quant_processor.validate_claim(
                    claim, download_result['path'], source_url=winning_url,
                    source_fetched_at=downloaded_at,
                )
                if result.verdict != Verdict.NOT_CHECKABLE:
                    result.flags.extend(self._reference_flags(citation_id))
                claim_results.append(result)
                logger.info(f"        Result: {result.verdict.value}")
                self.events.emit(
                    "claim_validated", claim_id=claim.claim_id,
                    verdict=result.verdict.value, confidence=result.confidence,
                )

            if not _KEEP_SOURCES:
                delete_result = self.dataset_downloader.delete_dataset(Path(download_result['path']).name)
                if delete_result['deleted']:
                    logger.info(f"    ✓ Deleted dataset to conserve memory: {download_result['path']}")
                    self.dataset_manifest.mark_deleted(str(citation_id))
                else:
                    logger.warning(f"    ⚠ Failed to delete dataset: {delete_result.get('error')}")
            else:
                logger.info(f"    ASV_KEEP_SOURCES set — retaining dataset: {download_result['path']}")

            batch_results.append(
                ValidationBatch(
                    citation_id=citation_id,
                    citation_text=first_claim.citation_text,
                    download_successful=True,
                    judgeable=True,
                    source_path=download_result['path'],
                    source_url=winning_url,
                    resolution_attempts=attempts,
                    reference_check=self.reference_checks.get(str(citation_id)),
                    claim_results=claim_results,
                    batch_notes=f"Validated {len(claim_results)} claims against the dataset"
                )
            )
            self.events.emit(
                "batch_finished", citation_id=str(citation_id), download_successful=True,
                num_claims=len(claims_group),
            )

        return batch_results

    def _process_paper_backed_quant(
        self, claims: List[ClaimObject]
    ) -> List[ValidationBatch]:
        """
        Paper-text flow for cited-quantitative claims.

        Mirrors ``_process_cited_qualitative`` — downloads the paper via
        ``TextDownloader.download_with_resolution`` and verifies each claim
        against the paper text via the qualitative RAG + LLM path. The result
        preserves ``claim_type="quantitative"`` on every ValidationResult (the
        qual_processor forwards ``claim.claim_type`` verbatim) so consumers can
        still segment quant vs. qual downstream.
        """
        batches = defaultdict(list)
        for claim in claims:
            batches[claim.citation_id].append(claim)

        batch_results = []

        for citation_id, claims_group in batches.items():
            logger.info(f"  [paper] Batch [{citation_id}]: {len(claims_group)} claims")
            self.events.emit(
                "batch_started", step="quantitative_cited",
                citation_id=str(citation_id), num_claims=len(claims_group),
            )
            first_claim = claims_group[0]

            raw_citation_text = self.citations_dict.get(str(citation_id), "")
            download_result = self.text_downloader.download_with_resolution(
                first_claim.citation_details, citation_id, raw_citation_text
            )

            attempts = [
                ResolutionAttempt(**a) for a in download_result.get('attempts', [])
            ]
            winning_url = download_result.get('winning_url')
            for a in attempts:
                self.events.emit(
                    "resolution_attempt", citation_id=str(citation_id), url=a.url,
                    source=a.source, downloaded=a.downloaded,
                )

            # Tier 0.3: three-way outcome. "Bytes arrived" and "the bytes are
            # evidence" are different questions, and collapsing them is what let
            # nine Nature landing pages be RAG-searched for evidence they could
            # not contain.
            judgeable, quality, reason, note = self._batch_outcome(download_result)

            downloaded_at = datetime.now().isoformat() if download_result.get('downloaded') else None
            manifest_entry = SourceManifestEntry(
                citation_id=str(citation_id),
                citation_text=first_claim.citation_text,
                raw_citation_text=raw_citation_text or None,
                citation_details=first_claim.citation_details,
                resolution_attempts=attempts,
                winning_url=winning_url,
                format=download_result.get('format'),
                content_quality=quality,
                content_signals=download_result.get('content_signals'),
                filename=Path(download_result['path']).name if download_result.get('path') else None,
                downloaded_at=downloaded_at,
                batch_num_claims=len(claims_group),
                batch_download_successful=bool(download_result.get('downloaded')),
                batch_judgeable=judgeable,
            )
            self.text_source_manifest.append(manifest_entry)

            if not judgeable:
                logger.warning(f"    ✗ {note}")
                batch_results.append(self._abstain_batch(
                    citation_id, first_claim, claims_group, reason, note,
                    attempts=attempts,
                    download_result=download_result,
                    method="rag_search",
                    quality=quality,
                ))
                self.events.emit(
                    "batch_finished", citation_id=str(citation_id),
                    download_successful=bool(download_result.get('downloaded')),
                    judgeable=False, num_claims=len(claims_group),
                )
                continue

            logger.info(f"    ✓ Full text obtained: {download_result['path']}")

            claim_results = []
            for claim in claims_group:
                logger.info(f"      Validating: {claim.claim_id}")
                result = self.qual_processor.validate_claim(
                    claim,
                    download_result.get('text_content'),
                    source_url=winning_url,
                    content_quality=quality,
                    source_fetched_at=downloaded_at,
                )
                if result.verdict != Verdict.NOT_CHECKABLE:
                    result.flags.extend(self._reference_flags(citation_id))
                claim_results.append(result)
                logger.info(f"        Result: {result.verdict.value}")
                self.events.emit(
                    "claim_validated", claim_id=claim.claim_id,
                    verdict=result.verdict.value, confidence=result.confidence,
                )

            if not _KEEP_SOURCES:
                delete_result = self.text_downloader.delete_text(Path(download_result['path']).name)
                if delete_result['deleted']:
                    logger.info(f"    ✓ Deleted text file to conserve memory: {download_result['path']}")
                    self.text_source_manifest.mark_deleted(str(citation_id))
                else:
                    logger.warning(f"    ⚠ Failed to delete text file: {delete_result.get('error')}")
            else:
                logger.info(f"    ASV_KEEP_SOURCES set — retaining text source: {download_result['path']}")

            batch_results.append(
                ValidationBatch(
                    citation_id=citation_id,
                    citation_text=first_claim.citation_text,
                    download_successful=True,
                    judgeable=True,
                    content_quality=quality,
                    source_path=download_result['path'],
                    source_url=winning_url,
                    resolution_attempts=attempts,
                    reference_check=self.reference_checks.get(str(citation_id)),
                    claim_results=claim_results,
                    batch_notes=f"Judged {len(claim_results)} claims against paper text"
                )
            )
            self.events.emit(
                "batch_finished", citation_id=str(citation_id), download_successful=True,
                num_claims=len(claims_group),
            )

        return batch_results

    def _process_cited_qualitative(self, claims: List[ClaimObject]) -> List[ValidationBatch]:
        """Process cited qualitative claims in citation batches."""
        batches = defaultdict(list)
        for claim in claims:
            batches[claim.citation_id].append(claim)

        batch_results = []

        for citation_id, claims_group in batches.items():
            logger.info(f"  Batch [{citation_id}]: {len(claims_group)} claims")
            self.events.emit(
                "batch_started", step="qualitative_cited",
                citation_id=str(citation_id), num_claims=len(claims_group),
            )
            first_claim = claims_group[0]

            raw_citation_text = self.citations_dict.get(str(citation_id), "")
            download_result = self.text_downloader.download_with_resolution(
                first_claim.citation_details, citation_id, raw_citation_text
            )

            attempts = [
                ResolutionAttempt(**a) for a in download_result.get('attempts', [])
            ]
            winning_url = download_result.get('winning_url')
            for a in attempts:
                self.events.emit(
                    "resolution_attempt", citation_id=str(citation_id), url=a.url,
                    source=a.source, downloaded=a.downloaded,
                )

            # Tier 0.3: three-way outcome. "Bytes arrived" and "the bytes are
            # evidence" are different questions, and collapsing them is what let
            # nine Nature landing pages be RAG-searched for evidence they could
            # not contain.
            judgeable, quality, reason, note = self._batch_outcome(download_result)

            downloaded_at = datetime.now().isoformat() if download_result.get('downloaded') else None
            manifest_entry = SourceManifestEntry(
                citation_id=str(citation_id),
                citation_text=first_claim.citation_text,
                raw_citation_text=raw_citation_text or None,
                citation_details=first_claim.citation_details,
                resolution_attempts=attempts,
                winning_url=winning_url,
                format=download_result.get('format'),
                content_quality=quality,
                content_signals=download_result.get('content_signals'),
                filename=Path(download_result['path']).name if download_result.get('path') else None,
                downloaded_at=downloaded_at,
                batch_num_claims=len(claims_group),
                batch_download_successful=bool(download_result.get('downloaded')),
                batch_judgeable=judgeable,
            )
            self.text_source_manifest.append(manifest_entry)

            if not judgeable:
                logger.warning(f"    ✗ {note}")
                batch_results.append(self._abstain_batch(
                    citation_id, first_claim, claims_group, reason, note,
                    attempts=attempts,
                    download_result=download_result,
                    method="rag_search",
                    quality=quality,
                ))
                self.events.emit(
                    "batch_finished", citation_id=str(citation_id),
                    download_successful=bool(download_result.get('downloaded')),
                    judgeable=False, num_claims=len(claims_group),
                )
                continue

            logger.info(f"    ✓ Full text obtained: {download_result['path']}")

            claim_results = []
            for claim in claims_group:
                logger.info(f"      Validating: {claim.claim_id}")
                result = self.qual_processor.validate_claim(
                    claim,
                    download_result.get('text_content'),
                    source_url=winning_url,
                    content_quality=quality,
                    source_fetched_at=downloaded_at,
                )
                if result.verdict != Verdict.NOT_CHECKABLE:
                    result.flags.extend(self._reference_flags(citation_id))
                claim_results.append(result)
                logger.info(f"        Result: {result.verdict.value}")
                self.events.emit(
                    "claim_validated", claim_id=claim.claim_id,
                    verdict=result.verdict.value, confidence=result.confidence,
                )

            if not _KEEP_SOURCES:
                delete_result = self.text_downloader.delete_text(Path(download_result['path']).name)
                if delete_result['deleted']:
                    logger.info(f"    ✓ Deleted text file to conserve memory: {download_result['path']}")
                    self.text_source_manifest.mark_deleted(str(citation_id))
                else:
                    logger.warning(f"    ⚠ Failed to delete text file: {delete_result.get('error')}")
            else:
                logger.info(f"    ASV_KEEP_SOURCES set — retaining text source: {download_result['path']}")

            batch_results.append(
                ValidationBatch(
                    citation_id=citation_id,
                    citation_text=first_claim.citation_text,
                    download_successful=True,
                    judgeable=True,
                    content_quality=quality,
                    source_path=download_result['path'],
                    source_url=winning_url,
                    resolution_attempts=attempts,
                    reference_check=self.reference_checks.get(str(citation_id)),
                    claim_results=claim_results,
                    batch_notes=f"Judged {len(claim_results)} claims against full text"
                )
            )
            self.events.emit(
                "batch_finished", citation_id=str(citation_id), download_successful=True,
                num_claims=len(claims_group),
            )

        return batch_results

    def _save_run_summary(
        self,
        claims: List[ClaimObject],
        results: Dict[str, Any],
        step_timings: Dict[str, float],
        run_start: float,
    ) -> None:
        """Save a structured JSON summary of the run for quick inspection."""

        def _flatten(result_list):
            for r in result_list:
                if isinstance(r, ValidationBatch):
                    yield from r.claim_results
                elif isinstance(r, ValidationResult):
                    yield r

        def _result_stats(result_list):
            """Per-step counts over the Tier 0.2 ontology.

            ``avg_confidence`` now averages only the results that *carry* a
            confidence. Abstentions have ``confidence=None`` by construction, so
            the old ``sum(confidences)/len(confidences)`` would raise — and
            averaging a zero in for every unchecked claim was what produced the
            "avg confidence 0.886" line that made an unsourced run look
            measured.
            """
            counts = {v.value: 0 for v in Verdict}
            reasons: Dict[str, int] = defaultdict(int)
            confidences: List[float] = []
            total = 0
            for cr in _flatten(result_list):
                total += 1
                counts[cr.verdict.value] += 1
                if cr.not_checkable_reason is not None:
                    reasons[cr.not_checkable_reason.value] += 1
                if cr.confidence is not None:
                    confidences.append(cr.confidence)

            checkable = total - counts[Verdict.NOT_CHECKABLE.value]
            avg_conf = round(sum(confidences) / len(confidences), 3) if confidences else None
            return {
                "count": total,
                "checkable": checkable,
                # Legacy field kept for one release so existing dashboards and
                # the compare view keep rendering; read `verdicts` instead.
                "passed": counts[Verdict.SUBSTANTIATED.value],
                "failed": counts[Verdict.NOT_SUBSTANTIATED.value]
                + counts[Verdict.CONTRADICTED.value],
                "avg_confidence": avg_conf,
                "verdicts": counts,
                "not_checkable_reasons": dict(sorted(reasons.items())),
            }

        total_elapsed = round(time.time() - run_start, 2)
        # B7: surface accumulated LLM cost/token usage on the run summary so
        # the frontend can show a cost column without parsing logs.
        try:
            cost = self.llm_client.get_cost_summary()
        except Exception as e:
            logger.warning(f"Could not compute cost summary: {e}")
            cost = None
        summary = {
            "run_timestamp": datetime.now().isoformat(),
            "log_file": str(self._log_path),
            "total_elapsed_seconds": total_elapsed,
            "cost": cost,
            "input": {
                "total_claims": len(claims),
                "qualitative_uncited": sum(1 for c in claims if c.claim_type == "qualitative" and not c.citation_id),
                "quantitative_uncited": sum(1 for c in claims if c.claim_type == "quantitative" and not c.citation_id),
                "qualitative_cited": sum(1 for c in claims if c.claim_type == "qualitative" and c.citation_id),
                "quantitative_cited": sum(1 for c in claims if c.claim_type == "quantitative" and c.citation_id),
            },
            "steps": {
                step: {
                    "elapsed_seconds": step_timings.get(step),
                    **_result_stats(results.get(step, [])),
                }
                for step in ["qualitative_uncited", "quantitative_uncited", "qualitative_cited", "quantitative_cited"]
            },
        }

        # Tier 0.2 — run-level verdict rollup. `substantiation_rate` is computed
        # over *checkable* claims only. The old `pass_rate` divided by
        # passed+failed, which on the measured run put 217 unsourced
        # plausibility passes in the numerator and called it 73%.
        all_results = [
            r
            for step in summary["steps"]
            for r in _flatten(results.get(step, []))
        ]
        verdict_totals = {v.value: 0 for v in Verdict}
        reason_totals: Dict[str, int] = defaultdict(int)
        evidenced = 0
        for r in all_results:
            verdict_totals[r.verdict.value] += 1
            if r.not_checkable_reason is not None:
                reason_totals[r.not_checkable_reason.value] += 1
            if r.evidence:
                evidenced += 1
        total_results = len(all_results)
        checkable = total_results - verdict_totals[Verdict.NOT_CHECKABLE.value]
        summary["verdicts"] = verdict_totals
        summary["not_checkable_reasons"] = dict(sorted(reason_totals.items()))
        summary["totals"] = {
            "claims": total_results,
            "checkable": checkable,
            "checkable_rate": round(checkable / total_results, 3) if total_results else None,
            "substantiated": verdict_totals[Verdict.SUBSTANTIATED.value],
            "substantiation_rate": (
                round(verdict_totals[Verdict.SUBSTANTIATED.value] / checkable, 3)
                if checkable else None
            ),
            "evidence_backed_verdicts": evidenced,
        }

        # Tier 0.6 — bibliography audit rollup.
        if self.reference_checks:
            ref_counts: Dict[str, int] = defaultdict(int)
            for check in self.reference_checks.values():
                ref_counts[check.status.value] += 1
                if check.retraction_status == RetractionStatus.RETRACTED:
                    ref_counts["retracted"] += 1
                elif check.retraction_status == RetractionStatus.CONCERN_RAISED:
                    ref_counts["concern_raised"] += 1
            summary["reference_audit"] = {
                "total": len(self.reference_checks),
                **dict(sorted(ref_counts.items())),
            }

        summary_path = self.run_paths.run_summary_json()
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)
        logger.info(f"✓ Run summary saved to: {summary_path}")

    def _save_results(self, results: Dict[str, Any]) -> None:
        """Save results to separate JSON files by claim type."""
        # Tier 0.2 / TIER0_PLAN.md §9: stamp the schema version once per run.
        # The result files stay plain JSON *lists* — every existing analysis
        # snippet (VALUE_PROPOSITION.md Appendix A) depends on that shape, and
        # the eight historical run folders are the evidence base for the
        # project's own published numbers. The API additionally treats any entry
        # without a `verdict` key as legacy, which handles the mixed-shape file
        # `revalidate_citation` can produce when retrying into an old run.
        try:
            with open(self.run_paths.results_schema_json(), "w", encoding="utf-8") as f:
                json.dump({
                    "schema_version": RESULT_SCHEMA_VERSION,
                    "written_at": datetime.now().isoformat(),
                }, f, indent=2)
        except Exception as e:
            logger.warning(f"Could not write results schema marker: {e}")

        for claim_type, validation_results in results.items():
            output_path = self.output_dir / f"{claim_type}_results.json"

            serialized_results = []
            for result in validation_results:
                if isinstance(result, ValidationBatch):
                    serialized_results.append(result.model_dump(mode="json"))
                elif isinstance(result, ValidationResult):
                    serialized_results.append(result.model_dump(mode="json"))
                else:
                    serialized_results.append(result)

            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(serialized_results, f, indent=2, ensure_ascii=False)

            logger.info(f"✓ Saved {claim_type} results to: {output_path}")

    def revalidate_citation(
        self,
        citation_id: str,
        claims_json_path: str,
        override_url: Optional[str] = None,
    ) -> Optional[ValidationBatch]:
        """
        Re-run validation for exactly the claims sharing ``citation_id`` — used
        by the web backend's "retry this citation" action (S3/S6) after a
        human supplies a working URL or fixes access, so a bad source doesn't
        require re-running the entire pipeline (B5).

        Reloads claims from ``claims_json_path`` (the citation_id → claims
        mapping is fixed at extraction time and doesn't change across a run),
        re-downloads/re-validates just that batch, and splices the result back
        into the appropriate ``validation_results/*_cited_results.json`` file
        on disk so subsequent reads of the run folder reflect the retry.

        Returns the produced ``ValidationBatch``, or ``None`` if the citation
        matched no claims.
        """
        claims, citations = self.load_claims_from_json(claims_json_path)
        self.citations_dict = citations
        group = [c for c in claims if c.citation_id == citation_id]
        if not group:
            raise ValueError(f"No claims found for citation_id={citation_id!r}")

        if override_url:
            for c in group:
                existing = c.citation_details
                c.citation_details = CitationDetails(
                    title=existing.title if existing else None,
                    authors=existing.authors if existing else None,
                    year=existing.year if existing else None,
                    url=override_url,
                    doi=existing.doi if existing else None,
                    raw_text=(existing.raw_text if existing else None)
                    or self.citations_dict.get(citation_id, override_url),
                )

        first = group[0]
        if first.claim_type == "quantitative" and first.found_source is not None:
            batches = self._process_dataset_backed_quant(group)
        elif first.claim_type == "quantitative":
            batches = self._process_paper_backed_quant(group)
        else:
            batches = self._process_cited_qualitative(group)

        batch = batches[0] if batches else None
        if batch is not None:
            self._merge_retry_into_results(batch)
        return batch

    def _merge_retry_into_results(self, batch: ValidationBatch) -> None:
        """Splice a retried batch back into its results JSON file on disk,
        replacing the stale entry for the same citation_id (or appending if
        this citation had no prior entry, e.g. a claim originally routed
        elsewhere)."""
        claim_type = batch.claim_results[0].claim_type if batch.claim_results else "qualitative"
        filename = (
            "qualitative_cited_results.json" if claim_type == "qualitative"
            else "quantitative_cited_results.json"
        )
        path = self.output_dir / filename
        existing: list = []
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                existing = json.load(f)

        replaced = False
        for i, entry in enumerate(existing):
            if entry.get("citation_id") == batch.citation_id:
                existing[i] = batch.model_dump(mode="json")
                replaced = True
                break
        if not replaced:
            existing.append(batch.model_dump(mode="json"))

        # TIER0_PLAN.md §9.4: a retry writes a Tier-0 batch into what may be a
        # pre-Tier-0 file. Rather than leave one file holding both shapes, stamp
        # the run as v2 — the API detects legacy *entries* individually, so the
        # untouched ones still read correctly.
        try:
            with open(self.run_paths.results_schema_json(), "w", encoding="utf-8") as f:
                json.dump({
                    "schema_version": RESULT_SCHEMA_VERSION,
                    "written_at": datetime.now().isoformat(),
                    "note": "upgraded in place by revalidate_citation",
                }, f, indent=2)
        except Exception as e:
            logger.warning(f"Could not write results schema marker: {e}")

        with open(path, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2, ensure_ascii=False)
        logger.info(f"✓ Retry result for citation [{batch.citation_id}] merged into {path}")

    @staticmethod
    def load_claims_from_json(json_path: str):
        """
        Load claims and citations from a JSON file produced by HybridClaimExtractor.
        The JSON is expected to have a top-level "claims" key and a "citations" key.
        Claims are returned in the order they appear in the file (already sorted by
        the extractor: qual_uncited → quant_uncited → qual_cited → quant_cited).

        Returns:
            Tuple[List[ClaimObject], Dict[str, str]] — claims and citations dict
        """
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        claims = [ClaimObject(**c) for c in data["claims"]]
        citations = data.get("citations", {})
        logger.info(f"Loaded {len(claims)} claims and {len(citations)} citations from {json_path}")
        return claims, citations


# Alias for backwards compatibility / README examples
ClaimValidator = ClaimOrchestrator