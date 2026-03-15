"""Claim Orchestrator - Main orchestration pipeline for claim validation"""

import json
import logging
from pathlib import Path
from typing import List, Dict, Any
from collections import defaultdict

from models import ClaimObject, ValidationResult, ValidationBatch, CitationDetails
from hybrid_citation_scraper.llm_client import LLMClient
from sourcefinder import DatasetFinder, TextFinder, DatasetDownloader, TextDownloader
from validator.truth_table_checker import TruthTableChecker
from validator.llm_verifier import LLMVerifier
from .process_quantitative import ProcessQuantitative
from .process_qualitative import ProcessQualitative
from validator.config import VALIDATION_OUTPUT_DIR

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ClaimOrchestrator:
    """Main orchestrator for claim validation"""

    def __init__(self, output_dir: str = VALIDATION_OUTPUT_DIR):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Initialize LLM client
        self.llm_client = LLMClient()

        # Initialize tool validators
        self.truth_table = TruthTableChecker()
        self.llm_verifier = LLMVerifier(self.llm_client)

        # Initialize process orchestrators
        self.quant_processor = ProcessQuantitative(self.llm_client)
        self.qual_processor = ProcessQualitative(self.llm_client)

        # Initialize sourcefinder tools
        self.dataset_finder = DatasetFinder(llm_client=self.llm_client)
        self.text_finder = TextFinder(llm_client=self.llm_client)
        self.dataset_downloader = DatasetDownloader()
        self.text_downloader = TextDownloader()

    def process_claims(self, claims: List[ClaimObject]) -> Dict[str, Any]:
        """
        Main processing pipeline following the specified order.
        Returns validation results grouped by claim type.
        """
        logger.info(f"\n{'='*60}")
        logger.info(f"Starting validation of {len(claims)} claims")
        logger.info(f"{'='*60}\n")

        results = {
            "qualitative_uncited": [],
            "quantitative_uncited": [],
            "qualitative_cited": [],
            "quantitative_cited": []
        }

        # Step 1: Qualitative without citation
        logger.info("Step 1: Processing qualitative claims without citations...")
        qual_uncited = [c for c in claims if c.claim_type == "qualitative" and not c.citation_id]
        results["qualitative_uncited"] = self._process_uncited_qualitative(qual_uncited)

        # Step 2: Quantitative without citation
        logger.info("\nStep 2: Processing quantitative claims without citations...")
        quant_uncited = [c for c in claims if c.claim_type == "quantitative" and not c.citation_id]
        quant_with_found_sources = self._process_uncited_quantitative(quant_uncited)

        # Step 3: Combine originally-uncited-now-cited + originally-cited quantitative
        logger.info("\nStep 3: Processing quantitative claims with citations...")
        quant_cited = [c for c in claims if c.claim_type == "quantitative" and c.citation_id]
        all_quant_cited = quant_with_found_sources + quant_cited
        results["quantitative_cited"] = self._process_cited_quantitative(all_quant_cited)

        # Step 4: Qualitative with citation
        logger.info("\nStep 4: Processing qualitative claims with citations...")
        qual_cited = [c for c in claims if c.claim_type == "qualitative" and c.citation_id]
        results["qualitative_cited"] = self._process_cited_qualitative(qual_cited)

        # Save results
        self._save_results(results)

        logger.info(f"\n{'='*60}")
        logger.info("Validation complete!")
        logger.info(f"{'='*60}\n")

        return results

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

    def _process_uncited_quantitative(self, claims: List[ClaimObject]) -> List[ClaimObject]:
        """
        Process quantitative claims without citations.
        - Truth Table + LLM Check
        - If not sufficiently answered, use sourcefinder
        - Append found sources to claims
        - DO NOT VALIDATE YET - return modified claims for later processing
        """
        modified_claims = []

        for claim in claims:
            logger.info(f"  Processing: {claim.claim_id}")

            tt_result = self.truth_table.check_claim(claim.text)
            llm_result = self.llm_verifier.verify_claim(claim.text)

            if (tt_result['found'] and tt_result['confidence'] > 0.8) or \
               (llm_result['plausible'] and llm_result['confidence'] > 0.8):
                logger.info("    Claim verified by truth table/LLM, skipping sourcefinder")
                modified_claims.append(claim)
                continue

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
            else:
                logger.warning("    ✗ No dataset found for claim")

            modified_claims.append(claim)

        return modified_claims

    def _process_cited_quantitative(self, claims: List[ClaimObject]) -> List[ValidationBatch]:
        """Process cited quantitative claims in citation batches."""
        batches = defaultdict(list)
        for claim in claims:
            batches[claim.citation_id].append(claim)

        batch_results = []

        for citation_id, claims_group in batches.items():
            logger.info(f"  Batch [{citation_id}]: {len(claims_group)} claims")
            first_claim = claims_group[0]

            if first_claim.citation_details and first_claim.citation_details.url:
                download_result = self.dataset_downloader.download(first_claim.citation_details.url, citation_id)
            else:
                download_result = {'downloaded': False, 'error': 'No URL found'}

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

            delete_result = self.dataset_downloader.delete_dataset(download_result['path'].split('/')[-1])
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

            if first_claim.citation_details and first_claim.citation_details.url:
                download_result = self.text_downloader.download(first_claim.citation_details.url, citation_id)
            else:
                download_result = {'downloaded': False, 'error': 'No URL found'}

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

            delete_result = self.text_downloader.delete_text(download_result['path'].split('/')[-1])
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