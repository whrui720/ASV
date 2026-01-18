"""
Claim Treatment Agent - Main orchestrator for Step 2

Routes claims from Step 1 to appropriate handlers based on claim type.
Processes claims through the treatment pipeline and outputs ClaimObjectAfterTreatment.
"""

import json
import logging
from typing import List, Dict, Any, Optional
from pathlib import Path

from .source_finder import SourceFinder
from .dataset_searcher import DatasetSearcher
from .text_downloader import TextDownloader
from .truth_table_checker import TruthTableChecker

# Import models from Step 1
from models import ClaimObject, ClaimObjectAfterTreatment, CitationSource
from hybrid_citation_scraper.llm_client import LLMClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ClaimTreatmentAgent:
    """
    Main orchestrator for Step 2: Claim Type Treatment
    
    Routes claims to appropriate handlers:
    - Quantitative + citation → SourceFinder (download dataset)
    - Quantitative + no citation → DatasetSearcher (find dataset)
    - Qualitative + citation (objective) → TextDownloader (download text)
    - Qualitative + no citation (subjective) → TruthTableChecker → LLM search
    
    Output: ClaimObjectAfterTreatment for each claim
    """
    
    def __init__(self, output_dir: str = "./treated_claims"):
        """
        Initialize the claim treatment agent.
        
        Args:
            output_dir: Directory to save outputs and downloaded sources
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize sub-agents
        self.llm_client = LLMClient()
        self.source_finder = SourceFinder(output_dir=str(self.output_dir / "datasets"))
        self.dataset_searcher = DatasetSearcher(llm_client=self.llm_client)
        self.text_downloader = TextDownloader(output_dir=str(self.output_dir / "texts"))
        self.truth_table_checker = TruthTableChecker(llm_client=self.llm_client)
        
        self.treated_claims = []
    
    def process_claims(self, claims: List[ClaimObject]) -> List[ClaimObjectAfterTreatment]:
        """
        Process a list of claims from Step 1.
        
        Args:
            claims: List of ClaimObject from hybrid_citation_scraper
            
        Returns:
            List of ClaimObjectAfterTreatment with sources mapped
        """
        logger.info(f"Processing {len(claims)} claims through treatment pipeline...")
        
        self.treated_claims = []
        
        for i, claim in enumerate(claims):
            logger.info(f"\n{'='*60}")
            logger.info(f"Processing claim {i+1}/{len(claims)}: {claim.claim_id}")
            logger.info(f"Type: {claim.claim_type}, Citation found: {claim.citation_found}")
            logger.info(f"Text: {claim.text[:100]}...")
            logger.info(f"{'='*60}")
            
            treated_claim = self._process_single_claim(claim)
            self.treated_claims.append(treated_claim)
        
        logger.info(f"\n✓ Completed processing {len(self.treated_claims)} claims")
        return self.treated_claims
    
    def _process_single_claim(self, claim: ClaimObject) -> ClaimObjectAfterTreatment:
        """
        Process a single claim based on its type and citation status.
        
        Returns ClaimObjectAfterTreatment with appropriate source mapping.
        """
        # Quantitative claim with citation
        if claim.claim_type == "quantitative" and claim.citation_found:
            return self._handle_quantitative_with_citation(claim)
        
        # Quantitative claim without citation
        elif claim.claim_type == "quantitative" and not claim.citation_found:
            return self._handle_quantitative_without_citation(claim)
        
        # Qualitative claim with citation (objective)
        elif claim.claim_type == "qualitative" and claim.citation_found:
            if "objective" in claim.classification:
                return self._handle_qualitative_objective_with_citation(claim)
            else:
                # Subjective but cited - still download the source
                return self._handle_qualitative_objective_with_citation(claim)
        
        # Qualitative claim without citation (subjective)
        elif claim.claim_type == "qualitative" and not claim.citation_found:
            return self._handle_qualitative_subjective_without_citation(claim)
        
        # Fallback for unexpected cases
        else:
            logger.warning(f"Unexpected claim configuration: {claim.claim_type}, citation={claim.citation_found}")
            return ClaimObjectAfterTreatment(
                claim_id=claim.claim_id,
                text=claim.text,
                claim_type=claim.claim_type,
                citation_mapped=False,
                citation_source=None,
                treatment_notes="Unexpected claim configuration - no treatment applied"
            )
    
    def _handle_quantitative_with_citation(self, claim: ClaimObject) -> ClaimObjectAfterTreatment:
        """
        Handle: Quantitative claim with citation found
        Action: Download dataset from citation
        """
        logger.info("→ Quantitative + Citation: Downloading dataset...")
        
        # Try to download from citation details
        if claim.citation_details:
            citation_dict = claim.citation_details.model_dump() if hasattr(claim.citation_details, 'model_dump') else claim.citation_details.__dict__
            download_result = self.source_finder.download_from_citation(
                citation_dict,
                claim.claim_id
            )
        else:
            download_result = {
                'downloaded': False,
                'error': 'No citation details available'
            }
        
        # Build CitationSource
        citation_source = CitationSource(
            downloaded=download_result['downloaded'],
            data_format=download_result.get('data_format'),
            platform=download_result.get('platform'),
            source_url=download_result.get('source_url'),
            local_path=download_result.get('local_path')
        )
        
        notes = "Citation found and dataset downloaded for validation." if download_result['downloaded'] else f"Citation found but download failed: {download_result.get('error', 'Unknown error')}"
        
        return ClaimObjectAfterTreatment(
            claim_id=claim.claim_id,
            text=claim.text,
            claim_type=claim.claim_type,
            citation_mapped=download_result['downloaded'],
            citation_source=citation_source,
            treatment_notes=notes
        )
    
    def _handle_quantitative_without_citation(self, claim: ClaimObject) -> ClaimObjectAfterTreatment:
        """
        Handle: Quantitative claim without citation
        Action: Search for relevant dataset
        """
        logger.info("→ Quantitative + No Citation: Searching for dataset...")
        
        # Search for datasets
        best_match = self.dataset_searcher.get_best_match(claim.text)
        
        if best_match:
            logger.info(f"Found potential dataset: {best_match['title']}")
            
            # Try to download the found dataset
            download_result = self.source_finder.download_dataset(
                best_match['url'],
                claim.claim_id
            )
            
            citation_source = CitationSource(
                downloaded=download_result['downloaded'],
                data_format=download_result.get('data_format'),
                platform=download_result.get('platform'),
                source_url=download_result.get('source_url'),
                local_path=download_result.get('local_path')
            )
            
            notes = f"No citation found. Searched and found dataset: '{best_match['title']}' (relevance: {best_match['relevance_score']:.2f}). "
            notes += "Dataset downloaded." if download_result['downloaded'] else f"Download failed: {download_result.get('error')}"
            
            return ClaimObjectAfterTreatment(
                claim_id=claim.claim_id,
                text=claim.text,
                claim_type=claim.claim_type,
                citation_mapped=download_result['downloaded'],
                citation_source=citation_source,
                treatment_notes=notes
            )
        else:
            logger.warning("No relevant dataset found")
            return ClaimObjectAfterTreatment(
                claim_id=claim.claim_id,
                text=claim.text,
                claim_type=claim.claim_type,
                citation_mapped=False,
                citation_source=None,
                treatment_notes="No citation found and dataset search yielded no confident matches."
            )
    
    def _handle_qualitative_objective_with_citation(self, claim: ClaimObject) -> ClaimObjectAfterTreatment:
        """
        Handle: Qualitative objective claim with citation
        Action: Download raw text from citation
        """
        logger.info("→ Qualitative + Citation: Downloading text source...")
        
        # Try to download from citation details
        if claim.citation_details:
            citation_dict = claim.citation_details.model_dump() if hasattr(claim.citation_details, 'model_dump') else claim.citation_details.__dict__
            download_result = self.text_downloader.download_from_citation(
                citation_dict,
                claim.claim_id
            )
        else:
            download_result = {
                'downloaded': False,
                'error': 'No citation details available'
            }
        
        # Build CitationSource
        citation_source = CitationSource(
            downloaded=download_result['downloaded'],
            data_format=download_result.get('data_format'),
            platform=download_result.get('platform', 'text'),
            source_url=download_result.get('source_url'),
            local_path=download_result.get('local_path')
        )
        
        notes = "Citation found and text source downloaded for validation." if download_result['downloaded'] else f"Citation found but download failed: {download_result.get('error', 'Unknown error')}"
        
        return ClaimObjectAfterTreatment(
            claim_id=claim.claim_id,
            text=claim.text,
            claim_type=claim.claim_type,
            citation_mapped=download_result['downloaded'],
            citation_source=citation_source,
            treatment_notes=notes
        )
    
    def _handle_qualitative_subjective_without_citation(self, claim: ClaimObject) -> ClaimObjectAfterTreatment:
        """
        Handle: Qualitative subjective claim without citation
        Action: Query truth table, fallback to LLM search
        """
        logger.info("→ Qualitative Subjective + No Citation: Checking truth tables...")
        
        # Check truth tables
        truth_result = self.truth_table_checker.check_claim(claim.text)
        
        if truth_result['found'] and truth_result['confidence'] > 0.5:
            logger.info(f"Truth table hit: {truth_result['rating']} (confidence: {truth_result['confidence']})")
            
            # Create a "virtual" citation source for the truth table result
            source_info = json.dumps(truth_result['sources'][:3]) if truth_result['sources'] else "Truth database"
            
            citation_source = CitationSource(
                downloaded=True,
                data_format='json',
                platform='truth_table',
                source_url=source_info,
                local_path=None
            )
            
            notes = f"No citation found. Truth table check: {truth_result['rating']} (method: {truth_result['method']}, confidence: {truth_result['confidence']:.2f}). "
            notes += f"Sources: {len(truth_result['sources'])} fact-check(s). {truth_result['explanation'][:100]}"
            
            return ClaimObjectAfterTreatment(
                claim_id=claim.claim_id,
                text=claim.text,
                claim_type=claim.claim_type,
                citation_mapped=True,
                citation_source=citation_source,
                treatment_notes=notes
            )
        else:
            logger.warning("No confident verification found")
            return ClaimObjectAfterTreatment(
                claim_id=claim.claim_id,
                text=claim.text,
                claim_type=claim.claim_type,
                citation_mapped=False,
                citation_source=None,
                treatment_notes=f"No citation found and truth table check inconclusive (confidence: {truth_result.get('confidence', 0):.2f}). Manual verification recommended."
            )
    
    def save_results(self, output_file: str = "treated_claims.json"):
        """
        Save treated claims to JSON file.
        
        Args:
            output_file: Filename for output (relative to output_dir)
        """
        output_path = self.output_dir / output_file
        
        # Convert to dict for JSON serialization
        claims_data = []
        for claim in self.treated_claims:
            claim_dict = claim.model_dump() if hasattr(claim, 'model_dump') else claim.__dict__
            claims_data.append(claim_dict)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(claims_data, f, indent=2, default=str)
        
        logger.info(f"✓ Saved {len(claims_data)} treated claims to {output_path}")
        return output_path
    
    def load_claims_from_step1(self, step1_output_file: str) -> List[ClaimObject]:
        """
        Load claims from Step 1 output file.
        
        Args:
            step1_output_file: Path to JSON file from hybrid_citation_scraper
            
        Returns:
            List of ClaimObject instances
        """
        with open(step1_output_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        claims = []
        for claim_data in data:
            claim = ClaimObject(**claim_data)
            claims.append(claim)
        
        logger.info(f"Loaded {len(claims)} claims from {step1_output_file}")
        return claims


def main():
    """
    Example usage of ClaimTreatmentAgent
    """
    import argparse
    
    parser = argparse.ArgumentParser(description="Process claims from Step 1 through treatment pipeline")
    parser.add_argument('input_file', help="JSON file containing claims from Step 1")
    parser.add_argument('--output-dir', default='./treated_claims', help="Output directory")
    args = parser.parse_args()
    
    # Initialize agent
    agent = ClaimTreatmentAgent(output_dir=args.output_dir)
    
    # Load claims from Step 1
    claims = agent.load_claims_from_step1(args.input_file)
    
    # Process claims
    treated_claims = agent.process_claims(claims)
    
    # Save results
    output_path = agent.save_results()
    
    print(f"\n{'='*60}")
    print(f"✓ Processing complete!")
    print(f"Treated {len(treated_claims)} claims")
    print(f"Output saved to: {output_path}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
