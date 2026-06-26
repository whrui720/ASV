"""Claim Orchestrator - Main orchestration pipeline for claim validation"""

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Tuple
from collections import defaultdict

from models import ClaimObject, ValidationResult, ValidationBatch, CitationDetails
from hybrid_citation_scraper.llm_client import LLMClient
from run_paths import RunPaths
from sourcefinder import DatasetFinder, TextFinder, DatasetDownloader, TextDownloader
from sourcefinder.browser_searcher import BrowserSearcher
from sourcefinder.config import KNOWN_PAYWALL_DOMAINS
from validator.truth_table_checker import TruthTableChecker
from validator.llm_verifier import LLMVerifier
from .process_quantitative import ProcessQuantitative
from .process_qualitative import ProcessQualitative

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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

    def __init__(self, run_paths: RunPaths):
        self.run_paths = run_paths
        self.output_dir = run_paths.validation_results

        self._log_path = _setup_file_logging(run_paths.orchestration_log())
        logger.info(f"Orchestrator initialised. Run folder: {run_paths.root}")
        logger.info(f"Log file: {self._log_path}")

        # Initialize LLM client
        self.llm_client = LLMClient()

        # Initialize tool validators
        self.truth_table = TruthTableChecker()
        self.llm_verifier = LLMVerifier(self.llm_client)

        # Initialize process orchestrators
        self.quant_processor = ProcessQuantitative(self.llm_client, run_paths=run_paths)
        self.qual_processor = ProcessQualitative(self.llm_client)

        # Initialize sourcefinder tools
        self.dataset_finder = DatasetFinder(llm_client=self.llm_client, run_paths=run_paths)
        self.text_finder = TextFinder(llm_client=self.llm_client, run_paths=run_paths)
        self.dataset_downloader = DatasetDownloader(run_paths=run_paths)
        self.text_downloader = TextDownloader(run_paths=run_paths)

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

        self._setup_browser_searcher(claims, citations or {})

        run_start = time.time()
        logger.info(f"\n{'='*60}")
        logger.info(f"Starting validation of {len(claims)} claims")
        logger.info(f"{'='*60}\n")

        results = {
            "qualitative_uncited": [],
            "quantitative_uncited": [],
            "qualitative_cited": [],
            "quantitative_cited": []
        }
        step_timings: Dict[str, float] = {}

        # Step 1: Qualitative without citation
        logger.info("Step 1: Processing qualitative claims without citations...")
        qual_uncited = [c for c in claims if c.claim_type == "qualitative" and not c.citation_id]
        t0 = time.time()
        results["qualitative_uncited"] = self._process_uncited_qualitative(qual_uncited)
        step_timings["qualitative_uncited"] = round(time.time() - t0, 2)

        # Step 2: Quantitative without citation.
        # Splits into (a) claims with a dataset source found — routed to Step 4, and
        # (b) terminal direct_results (truth-table/LLM verified OR no source found) —
        # written directly to quantitative_uncited_results.json.
        logger.info("\nStep 2: Processing quantitative claims without citations...")
        quant_uncited = [c for c in claims if c.claim_type == "quantitative" and not c.citation_id]
        t0 = time.time()
        quant_with_found_sources, quant_uncited_direct_results = \
            self._process_uncited_quantitative(quant_uncited)
        results["quantitative_uncited"] = quant_uncited_direct_results
        step_timings["quantitative_uncited"] = round(time.time() - t0, 2)

        # Step 3: Qualitative with citation (matches README ordering: qual cited before quant cited)
        logger.info("\nStep 3: Processing qualitative claims with citations...")
        qual_cited = [c for c in claims if c.claim_type == "qualitative" and c.citation_id]
        t0 = time.time()
        results["qualitative_cited"] = self._process_cited_qualitative(qual_cited)
        step_timings["qualitative_cited"] = round(time.time() - t0, 2)

        # Step 4: Combine originally-uncited-now-cited + originally-cited quantitative.
        # quant_with_found_sources already only contains claims that resolved a dataset.
        logger.info("\nStep 4: Processing quantitative claims with citations...")
        quant_cited = [c for c in claims if c.claim_type == "quantitative" and c.citation_id]
        all_quant_cited = quant_with_found_sources + quant_cited
        t0 = time.time()
        results["quantitative_cited"] = self._process_cited_quantitative(all_quant_cited)
        step_timings["quantitative_cited"] = round(time.time() - t0, 2)

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

        return results

    def _setup_browser_searcher(
        self, claims: List[ClaimObject], citations: Dict[str, str]
    ) -> None:
        """
        Start a BrowserSearcher and — if any cited sources are behind known paywalls —
        open those domains in the browser so the user can log in manually before
        the pipeline begins processing.

        After this method returns, self.browser_searcher is set and injected into all
        finders that support it.
        """
        self.browser_searcher = BrowserSearcher(llm_client=self.llm_client)

        # Inject into all finders so they use the same authenticated browser session
        self.dataset_finder.browser_searcher = self.browser_searcher
        self.text_finder.browser_searcher = self.browser_searcher
        self.text_downloader._paper_finder.browser_searcher = self.browser_searcher

        # Detect which paywall domains appear in the citation text or claim URLs
        all_text = " ".join(citations.values())
        for claim in claims:
            if claim.citation_details and claim.citation_details.url:
                all_text += " " + claim.citation_details.url

        paywall_domains_needed = [
            domain for domain in KNOWN_PAYWALL_DOMAINS
            if domain in all_text.lower()
        ]

        if not paywall_domains_needed:
            logger.info("No known paywall domains detected in citations — browser ready (no login needed)")
            return

        logger.info(
            f"Paywall domains detected in citations: {paywall_domains_needed}\n"
            "Opening browser tabs for manual login..."
        )
        self.browser_searcher.open_domains(paywall_domains_needed)
        print(
            f"\n[ASV] Please log in to the following sites in the browser window:\n"
            f"  {', '.join(paywall_domains_needed)}\n"
            "Press Enter here when done to continue the pipeline..."
        )
        input()
        logger.info("User completed login — continuing pipeline")

    def _process_uncited_qualitative(self, claims: List[ClaimObject]) -> List[ValidationResult]:
        """Process qualitative claims without citations: Truth Table + LLM Check"""
        results = []

        for claim in claims:
            logger.info(f"  Validating: {claim.claim_id}")

            tt_result = self.truth_table.check_claim(claim.text)
            llm_result = self.llm_verifier.verify_claim(claim.text)

            passed = tt_result['found'] or llm_result['plausible']
            confidence = max(tt_result['confidence'], llm_result['confidence'])

            explanation = f"Truth Table: {tt_result['explanation']}. LLM Check: {llm_result['reasoning']}"

            validation = ValidationResult(
                claim_id=claim.claim_id,
                claim_type=claim.claim_type,
                originally_uncited=False,
                validated=True,
                validation_method="truth_table+llm_check",
                confidence=confidence,
                passed=passed,
                explanation=explanation,
                sources_used=tt_result.get('sources', [])
            )
            results.append(validation)

            logger.info(f"    Result: {'PASSED' if passed else 'FAILED'} (confidence: {confidence:.2f})")

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
          - direct_results: ValidationResults for the two terminal branches that
            do NOT proceed further (truth-table/LLM verified, and no-dataset-found).
            These land directly in quantitative_uncited_results.json.
        """
        claims_to_route: List[ClaimObject] = []
        direct_results: List[ValidationResult] = []

        for claim in claims:
            logger.info(f"  Processing: {claim.claim_id}")

            tt_result = self.truth_table.check_claim(claim.text)
            llm_result = self.llm_verifier.verify_claim(claim.text)

            # Branch A: Truth-table / LLM strongly verified — no dataset needed.
            if (tt_result['found'] and tt_result['confidence'] > 0.8) or \
               (llm_result['plausible'] and llm_result['confidence'] > 0.8):
                logger.info("    Claim verified by truth table/LLM, skipping sourcefinder")
                passed = tt_result['found'] or llm_result['plausible']
                confidence = max(tt_result['confidence'], llm_result['confidence'])
                explanation = (
                    f"Truth Table: {tt_result['explanation']}. "
                    f"LLM Check: {llm_result['reasoning']}"
                )
                direct_results.append(ValidationResult(
                    claim_id=claim.claim_id,
                    claim_type=claim.claim_type,
                    originally_uncited=False,
                    validated=True,
                    validation_method="truth_table+llm_only",
                    confidence=confidence,
                    passed=passed,
                    explanation=explanation,
                    sources_used=tt_result.get('sources', []),
                ))
                logger.info(f"    Result: {'PASSED' if passed else 'FAILED'} (confidence: {confidence:.2f})")
                continue

            # Branch B: Try sourcefinder.
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
                direct_results.append(ValidationResult(
                    claim_id=claim.claim_id,
                    claim_type=claim.claim_type,
                    originally_uncited=True,
                    validated=False,
                    validation_method="source_not_found",
                    confidence=0.0,
                    passed=False,
                    explanation="No dataset source could be located for this uncited quantitative claim.",
                    sources_used=[],
                ))

        return claims_to_route, direct_results

    def _process_cited_quantitative(self, claims: List[ClaimObject]) -> List[ValidationBatch]:
        """Process cited quantitative claims in citation batches."""
        batches = defaultdict(list)
        for claim in claims:
            batches[claim.citation_id].append(claim)

        batch_results = []

        for citation_id, claims_group in batches.items():
            logger.info(f"  Batch [{citation_id}]: {len(claims_group)} claims")
            first_claim = claims_group[0]

            # Resolve URL: use known URL → open-access resolution → give up
            url = first_claim.citation_details.url if first_claim.citation_details else None
            if not url:
                raw_citation_text = self.citations_dict.get(str(citation_id), "")
                url = self.text_downloader._paper_finder.find_url(raw_citation_text)

            if url:
                download_result = self.dataset_downloader.download(url, citation_id)
            else:
                download_result = {'downloaded': False, 'error': 'No URL found via open-access APIs'}

            if not download_result['downloaded']:
                logger.error(f"    ✗ Download failed: {download_result.get('error')}")
                claim_results = []
                for claim in claims_group:
                    claim_results.append(
                        ValidationResult(
                            claim_id=claim.claim_id,
                            claim_type=claim.claim_type,
                            originally_uncited=claim.originally_uncited,
                            validated=False,
                            validation_method="python_script",
                            confidence=0.0,
                            passed=False,
                            explanation="Batch failed: dataset download unsuccessful",
                            sources_used=[],
                            errors=download_result.get('error')
                        )
                    )

                batch_results.append(
                    ValidationBatch(
                        citation_id=citation_id,
                        citation_text=first_claim.citation_text,
                        download_successful=False,
                        source_path=None,
                        claim_results=claim_results,
                        batch_notes=f"Download failed: {download_result.get('error')}"
                    )
                )
                continue

            logger.info(f"    ✓ Downloaded dataset: {download_result['path']}")

            claim_results = []
            for claim in claims_group:
                logger.info(f"      Validating: {claim.claim_id}")
                result = self.quant_processor.validate_claim(claim, download_result['path'])
                claim_results.append(result)
                logger.info(f"        Result: {'PASSED' if result.passed else 'FAILED'}")

            delete_result = self.dataset_downloader.delete_dataset(Path(download_result['path']).name)
            if delete_result['deleted']:
                logger.info(f"    ✓ Deleted dataset to conserve memory: {download_result['path']}")
            else:
                logger.warning(f"    ⚠ Failed to delete dataset: {delete_result.get('error')}")

            batch_results.append(
                ValidationBatch(
                    citation_id=citation_id,
                    citation_text=first_claim.citation_text,
                    download_successful=True,
                    source_path=download_result['path'],
                    claim_results=claim_results,
                    batch_notes=f"Successfully validated {len(claim_results)} claims"
                )
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
            first_claim = claims_group[0]

            raw_citation_text = self.citations_dict.get(str(citation_id), "")
            download_result = self.text_downloader.download_with_resolution(
                first_claim.citation_details, citation_id, raw_citation_text
            )

            if not download_result['downloaded']:
                logger.error(f"    ✗ Download failed: {download_result.get('error')}")
                claim_results = []
                for claim in claims_group:
                    claim_results.append(
                        ValidationResult(
                            claim_id=claim.claim_id,
                            claim_type=claim.claim_type,
                            originally_uncited=claim.originally_uncited,
                            validated=False,
                            validation_method="rag_search",
                            confidence=0.0,
                            passed=False,
                            explanation="Batch failed: text source download unsuccessful",
                            sources_used=[],
                            errors=download_result.get('error')
                        )
                    )

                batch_results.append(
                    ValidationBatch(
                        citation_id=citation_id,
                        citation_text=first_claim.citation_text,
                        download_successful=False,
                        source_path=None,
                        claim_results=claim_results,
                        batch_notes=f"Download failed: {download_result.get('error')}"
                    )
                )
                continue

            logger.info(f"    ✓ Downloaded text: {download_result['path']}")

            claim_results = []
            for claim in claims_group:
                logger.info(f"      Validating: {claim.claim_id}")
                result = self.qual_processor.validate_claim(claim, download_result.get('text_content'))
                claim_results.append(result)
                logger.info(f"        Result: {'PASSED' if result.passed else 'FAILED'}")

            delete_result = self.text_downloader.delete_text(Path(download_result['path']).name)
            if delete_result['deleted']:
                logger.info(f"    ✓ Deleted text file to conserve memory: {download_result['path']}")
            else:
                logger.warning(f"    ⚠ Failed to delete text file: {delete_result.get('error')}")

            batch_results.append(
                ValidationBatch(
                    citation_id=citation_id,
                    citation_text=first_claim.citation_text,
                    download_successful=True,
                    source_path=download_result['path'],
                    claim_results=claim_results,
                    batch_notes=f"Successfully validated {len(claim_results)} claims"
                )
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

        def _result_stats(result_list):
            if not result_list:
                return {"count": 0, "passed": 0, "failed": 0, "avg_confidence": None}
            passed = failed = 0
            confidences = []
            for r in result_list:
                # ValidationBatch: look at claim_results inside
                if isinstance(r, ValidationBatch):
                    for cr in r.claim_results:
                        if cr.passed:
                            passed += 1
                        else:
                            failed += 1
                        confidences.append(cr.confidence)
                elif isinstance(r, ValidationResult):
                    if r.passed:
                        passed += 1
                    else:
                        failed += 1
                    confidences.append(r.confidence)
            avg_conf = round(sum(confidences) / len(confidences), 3) if confidences else None
            return {"count": passed + failed, "passed": passed, "failed": failed, "avg_confidence": avg_conf}

        total_elapsed = round(time.time() - run_start, 2)
        summary = {
            "run_timestamp": datetime.now().isoformat(),
            "log_file": str(self._log_path),
            "total_elapsed_seconds": total_elapsed,
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

        summary_path = self.run_paths.run_summary_json()
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)
        logger.info(f"✓ Run summary saved to: {summary_path}")

    def _save_results(self, results: Dict[str, Any]) -> None:
        """Save results to separate JSON files by claim type."""
        for claim_type, validation_results in results.items():
            output_path = self.output_dir / f"{claim_type}_results.json"

            serialized_results = []
            for result in validation_results:
                if isinstance(result, ValidationBatch):
                    serialized_results.append(result.model_dump())
                elif isinstance(result, ValidationResult):
                    serialized_results.append(result.model_dump())
                else:
                    serialized_results.append(result)

            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(serialized_results, f, indent=2, ensure_ascii=False)

            logger.info(f"✓ Saved {claim_type} results to: {output_path}")

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