"""
Hybrid Citation Scraper - Deterministic Pipeline with LLM Augmentation

Architecture:
- Deterministic citation parsing with LLM fallback
- Sentence-boundary text chunking to preserve claim integrity
- Single-shot LLM calls for structured claim extraction
- Deterministic citation mapping based on markers
"""

import json
from typing import List, Dict, Tuple
from pathlib import Path

from .utils import (
    extract_text_from_pdf,
    extract_title_and_abstract,
    locate_reference_section,
    detect_citation_style,
    parse_citations_deterministic,
    validate_citations,
    semantic_chunk_text
)
from .llm_client import LLMClient
from models import ClaimObject, CitationDetails


class HybridClaimExtractor:
    """
    Hybrid citation scraper using deterministic pipeline + LLM augmentation.
    
    Pipeline stages:
    1. Citation Extraction: Deterministic regex → LLM fallback
    2. Text Chunking: Sentence-boundary splitting with overlap
    3. Claim Extraction: Single-shot LLM calls with structured output
    4. Citation Mapping: Deterministic marker matching
    """
    
    def __init__(self):
        self.llm_client = LLMClient()
        self.citations = {}
        self.claims = []
        self.paper_title = None
        self.paper_abstract = None
    
    def extract_citations(self, pdf_path: str) -> Dict[str, str]:
        """
        Extract citations from PDF using hybrid approach.
        Returns dict mapping citation_id -> citation_text
        """
        print("Extracting text from PDF...")
        full_text = extract_text_from_pdf(pdf_path)
        
        print("Locating reference section...")
        ref_section = locate_reference_section(full_text)
        
        if not ref_section:
            print("⚠️  Could not locate reference section deterministically")
            print("Using LLM fallback to extract references...")
            # locate_reference_section already tried fallback, use full text
            self.citations = self.llm_client.parse_references_with_llm(full_text)
            return self.citations
        
        print("Detecting citation style...")
        citation_style = detect_citation_style(ref_section)
        
        if citation_style:
            print(f"✓ Detected {citation_style} citation format")
            print("Parsing citations deterministically...")
            try:
                citations = parse_citations_deterministic(ref_section, citation_style)
                
                if validate_citations(citations):
                    print(f"✓ Successfully parsed {len(citations)} citations")
                    self.citations = citations
                    return self.citations
                else:
                    print("⚠️  Parsed citations failed validation")
            except Exception as e:
                print(f"⚠️  Deterministic parsing failed: {e}")
        
        # Fallback to LLM
        print("Using LLM fallback to parse references...")
        self.citations = self.llm_client.parse_references_with_llm(ref_section)
        print(f"✓ LLM parsed {len(self.citations)} citations")
        
        return self.citations
    
    def extract_claims_from_text(self, text: str, chunk_size: int = 800) -> List[ClaimObject]:
        """
        Extract claims from text using LLM.
        Text is chunked for processing.
        Returns list of ClaimObject instances.
        """
        print("Chunking text for processing...")
        chunks = semantic_chunk_text(text, chunk_size=chunk_size)
        print(f"Created {len(chunks)} chunks")
        
        all_claims = []
        
        print("Extracting claims from chunks...")
        for i, chunk in enumerate(chunks):
            print(f"  Processing chunk {i+1}/{len(chunks)}...", end="\r")
            
            claims = self.llm_client.extract_claims_from_chunk(
                chunk['text'],
                chunk['chunk_id'],
                available_citations=self.citations,
                paper_title=self.paper_title,
                paper_abstract=self.paper_abstract
            )
            
            # Update location information
            for claim in claims:
                if claim.location_in_text:
                    claim.location_in_text.start += chunk['start_pos']
                    claim.location_in_text.end += chunk['start_pos']
            
            all_claims.extend(claims)
        
        print(f"\n✓ Extracted {len(all_claims)} claims")
        self.claims = all_claims
        
        return all_claims
    
    def map_citations_to_claims(self) -> List[ClaimObject]:
        """
        Map citation details to claims based on citation markers.
        Updates the claims with full citation details and citation_id.
        """
        print("Mapping citations to claims...")
        
        for claim in self.claims:
            if claim.citation_found and claim.citation_text:
                # Extract citation ID from marker
                citation_id = self._extract_citation_id(claim.citation_text)
                
                if citation_id and citation_id in self.citations:
                    # Store citation_id for batch processing downstream
                    claim.citation_id = citation_id
                    
                    # Create CitationDetails object
                    claim.citation_details = self._parse_citation_details(
                        self.citations[citation_id]
                    )
        
        mapped_count = sum(1 for c in self.claims if c.citation_details is not None)
        print(f"✓ Mapped {mapped_count}/{len(self.claims)} citations")
        
        return self.claims
    
    def process_pdf(self, pdf_path: str) -> Tuple[List[ClaimObject], Dict[str, str]]:
        """
        Complete processing pipeline for a PDF.
        Returns (claims, citations)
        """
        print(f"\n{'='*60}")
        print(f"Processing: {Path(pdf_path).name}")
        print(f"{'='*60}\n")
        
        # Extract text
        full_text = extract_text_from_pdf(pdf_path)
        
        # Extract title and abstract for context
        print("Extracting title and abstract...")
        paper_metadata = extract_title_and_abstract(full_text)
        self.paper_title = paper_metadata['title']
        self.paper_abstract = paper_metadata['abstract']
        
        if self.paper_title:
            print(f"✓ Title: {self.paper_title[:80]}...")
        if self.paper_abstract:
            print(f"✓ Abstract: {self.paper_abstract[:100]}...")
        
        # Extract citations
        self.extract_citations(pdf_path)
        
        # Remove reference section from text before claim extraction
        ref_section = locate_reference_section(full_text)
        if ref_section:
            # Extract only the body text (before references)
            body_text = full_text[:full_text.find(ref_section)]
        else:
            # Use first 70% if we can't find reference section
            body_text = full_text[:int(len(full_text) * 0.7)]
        
        # Extract claims
        self.extract_claims_from_text(body_text)
        
        # Map citations to claims
        self.map_citations_to_claims()
        
        # Print cost summary
        print(f"\n{'='*60}")
        print("Cost Summary:")
        cost_info = self.llm_client.get_cost_summary()
        print(f"  Input tokens:  {cost_info['input_tokens']:,}")
        print(f"  Output tokens: {cost_info['output_tokens']:,}")
        print(f"  Total cost:    ${cost_info['total_cost']:.4f}")
        print(f"{'='*60}\n")
        
        return self.claims, self.citations
    
    def get_claims_by_citation(self) -> Dict[str, List[ClaimObject]]:
        """
        Group claims by citation_id for batch processing.
        
        Returns:
            Dict mapping citation_id -> list of claims using that citation.
            Claims without citations are grouped under "_no_citation" key.
            
        Usage:
            claims_by_citation = extractor.get_claims_by_citation()
            for citation_id, claims_group in claims_by_citation.items():
                # Download citation source once
                # Validate all claims in claims_group
        """
        from collections import defaultdict
        
        batched = defaultdict(list)
        uncited = []
        
        for claim in self.claims:
            if claim.citation_id:
                batched[claim.citation_id].append(claim)
            else:
                uncited.append(claim)
        
        # Add uncited claims under special key
        if uncited:
            batched["_no_citation"] = uncited
        
        return dict(batched)
    
    def save_results(self, output_path: str):
        """Save claims to JSON file"""
        output_data = {
            "claims": [claim.model_dump() for claim in self.claims],
            "citations": self.citations,
            "summary": {
                "total_claims": len(self.claims),
                "quantitative_claims": sum(1 for c in self.claims if c.claim_type == "quantitative"),
                "qualitative_claims": sum(1 for c in self.claims if c.claim_type == "qualitative"),
                "claims_with_citations": sum(1 for c in self.claims if c.citation_found),
            }
        }
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
        
        print(f"✓ Results saved to {output_path}")
    
    @staticmethod
    def _extract_citation_id(citation_marker: str) -> str:
        """Extract citation ID from marker like [1] or (Smith, 2020)"""
        import re
        
        # Numeric citation: [1] -> "1"
        numeric_match = re.search(r'\[(\d+)\]', citation_marker)
        if numeric_match:
            return numeric_match.group(1)
        
        # Author-year: (Smith, 2020) -> "Smith"
        author_match = re.search(r'\(([A-Z][a-z]+)', citation_marker)
        if author_match:
            return author_match.group(1)
        
        return citation_marker.strip('[]()').strip()
    
    @staticmethod
    def _parse_citation_details(citation_text: str) -> CitationDetails:
        """Parse citation text into structured details"""
        import re
        
        # Try to extract common fields
        title = None
        authors = []
        year = None
        url = None
        doi = None
        
        # Extract year
        year_match = re.search(r'\((\d{4})\)|(\d{4})', citation_text)
        if year_match:
            year = int(year_match.group(1) or year_match.group(2))
        
        # Extract DOI
        doi_match = re.search(r'doi[:\s]*(10\.\S+)', citation_text, re.IGNORECASE)
        if doi_match:
            doi = doi_match.group(1).rstrip('.')
        
        # Extract URL
        url_match = re.search(r'https?://\S+', citation_text)
        if url_match:
            url = url_match.group(0).rstrip('.,;')
        
        # Simple author extraction (first part before year)
        if year_match:
            author_part = citation_text[:year_match.start()].strip()
            # Split by common delimiters
            author_part = re.split(r'[,;&]', author_part)[0]
            if author_part:
                authors = [author_part.strip().rstrip('.')]
        
        return CitationDetails(
            title=title,
            authors=authors if authors else None,
            year=year,
            url=url,
            doi=doi,
            raw_text=citation_text
        )


def main():
    """Example usage"""
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python -m hybrid_citation_scraper.claim_extractor <pdf_path>")
        sys.exit(1)
    
    pdf_path = sys.argv[1]
    
    if not Path(pdf_path).exists():
        print(f"Error: File not found: {pdf_path}")
        sys.exit(1)
    
    # Create extractor
    extractor = HybridClaimExtractor()
    
    # Process PDF
    claims, citations = extractor.process_pdf(pdf_path)
    
    # Save results
    output_path = Path(pdf_path).stem + "_claims.json"
    extractor.save_results(output_path)
    
    # Print summary
    print(f"\nSummary:")
    print(f"  Total claims: {len(claims)}")
    print(f"  Quantitative: {sum(1 for c in claims if c.claim_type == 'quantitative')}")
    print(f"  Qualitative: {sum(1 for c in claims if c.claim_type == 'qualitative')}")
    print(f"  With citations: {sum(1 for c in claims if c.citation_found)}")


if __name__ == "__main__":
    main()
