"""Tests for hybrid_citation_scraper.claim_extractor module"""

import pytest
import json
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path
from hybrid_citation_scraper.claim_extractor import HybridClaimExtractor
from models import ClaimObject, CitationDetails, LocationInText


class TestHybridClaimExtractorInit:
    """Tests for HybridClaimExtractor initialization"""
    
    @patch('hybrid_citation_scraper.claim_extractor.LLMClient')
    def test_init_creates_llm_client(self, mock_llm_client):
        """Test that extractor initializes LLM client"""
        extractor = HybridClaimExtractor()
        assert mock_llm_client.called
        assert hasattr(extractor, 'llm_client')
        assert extractor.citations == {}
        assert extractor.claims == []
    
    @patch('hybrid_citation_scraper.claim_extractor.LLMClient')
    def test_init_sets_default_values(self, mock_llm_client):
        """Test that extractor sets default values"""
        extractor = HybridClaimExtractor()
        assert extractor.paper_title is None
        assert extractor.paper_abstract is None


class TestExtractCitations:
    """Tests for extract_citations method"""
    
    @patch('hybrid_citation_scraper.claim_extractor.LLMClient')
    @patch('hybrid_citation_scraper.claim_extractor.extract_text_from_pdf')
    @patch('hybrid_citation_scraper.claim_extractor.locate_reference_section')
    @patch('hybrid_citation_scraper.claim_extractor.detect_citation_style')
    @patch('hybrid_citation_scraper.claim_extractor.parse_citations_deterministic')
    @patch('hybrid_citation_scraper.claim_extractor.validate_citations')
    def test_extract_citations_deterministic_success(
        self, mock_validate, mock_parse, mock_detect, 
        mock_locate, mock_extract_text, mock_llm_client,
        sample_pdf_text, sample_references_section, sample_citations_dict
    ):
        """Test successful deterministic citation extraction"""
        mock_extract_text.return_value = sample_pdf_text
        mock_locate.return_value = sample_references_section
        mock_detect.return_value = 'numeric'
        mock_parse.return_value = sample_citations_dict
        mock_validate.return_value = True
        
        extractor = HybridClaimExtractor()
        result = extractor.extract_citations("test.pdf")
        
        assert result == sample_citations_dict
        assert extractor.citations == sample_citations_dict
        mock_parse.assert_called_once()
    
    @patch('hybrid_citation_scraper.claim_extractor.LLMClient')
    @patch('hybrid_citation_scraper.claim_extractor.extract_text_from_pdf')
    @patch('hybrid_citation_scraper.claim_extractor.locate_reference_section')
    def test_extract_citations_no_ref_section(
        self, mock_locate, mock_extract_text, mock_llm_client, sample_pdf_text
    ):
        """Test fallback to LLM when reference section not found"""
        mock_extract_text.return_value = sample_pdf_text
        mock_locate.return_value = None
        
        mock_llm_instance = mock_llm_client.return_value
        mock_llm_instance.parse_references_with_llm.return_value = {"1": "Citation"}
        
        extractor = HybridClaimExtractor()
        result = extractor.extract_citations("test.pdf")
        
        # Should fall back to LLM
        mock_llm_instance.parse_references_with_llm.assert_called_once()
        assert result == {"1": "Citation"}
    
    @patch('hybrid_citation_scraper.claim_extractor.LLMClient')
    @patch('hybrid_citation_scraper.claim_extractor.extract_text_from_pdf')
    @patch('hybrid_citation_scraper.claim_extractor.locate_reference_section')
    @patch('hybrid_citation_scraper.claim_extractor.detect_citation_style')
    def test_extract_citations_undetected_style(
        self, mock_detect, mock_locate, mock_extract_text, 
        mock_llm_client, sample_pdf_text, sample_references_section
    ):
        """Test fallback to LLM when citation style cannot be detected"""
        mock_extract_text.return_value = sample_pdf_text
        mock_locate.return_value = sample_references_section
        mock_detect.return_value = None
        
        mock_llm_instance = mock_llm_client.return_value
        mock_llm_instance.parse_references_with_llm.return_value = {"1": "Citation"}
        
        extractor = HybridClaimExtractor()
        result = extractor.extract_citations("test.pdf")
        
        mock_llm_instance.parse_references_with_llm.assert_called_once()
    
    @patch('hybrid_citation_scraper.claim_extractor.LLMClient')
    @patch('hybrid_citation_scraper.claim_extractor.extract_text_from_pdf')
    @patch('hybrid_citation_scraper.claim_extractor.locate_reference_section')
    @patch('hybrid_citation_scraper.claim_extractor.detect_citation_style')
    @patch('hybrid_citation_scraper.claim_extractor.parse_citations_deterministic')
    @patch('hybrid_citation_scraper.claim_extractor.validate_citations')
    def test_extract_citations_validation_fails(
        self, mock_validate, mock_parse, mock_detect,
        mock_locate, mock_extract_text, mock_llm_client,
        sample_pdf_text, sample_references_section
    ):
        """Test fallback to LLM when validation fails"""
        mock_extract_text.return_value = sample_pdf_text
        mock_locate.return_value = sample_references_section
        mock_detect.return_value = 'numeric'
        mock_parse.return_value = {"1": "Too short"}
        mock_validate.return_value = False
        
        mock_llm_instance = mock_llm_client.return_value
        mock_llm_instance.parse_references_with_llm.return_value = {"1": "Better citation"}
        
        extractor = HybridClaimExtractor()
        result = extractor.extract_citations("test.pdf")
        
        mock_llm_instance.parse_references_with_llm.assert_called_once()


class TestExtractClaimsFromText:
    """Tests for extract_claims_from_text method"""
    
    @patch('hybrid_citation_scraper.claim_extractor.LLMClient')
    @patch('hybrid_citation_scraper.claim_extractor.semantic_chunk_text')
    def test_extract_claims_basic(
        self, mock_chunk, mock_llm_client, sample_claim_objects
    ):
        """Test basic claim extraction from text"""
        mock_chunk.return_value = [
            {'chunk_id': 0, 'text': 'Chunk 1', 'start_pos': 0, 'end_pos': 7, 'token_count': 2}
        ]
        
        mock_llm_instance = mock_llm_client.return_value
        mock_llm_instance.extract_claims_from_chunk.return_value = [sample_claim_objects[0]]
        
        extractor = HybridClaimExtractor()
        result = extractor.extract_claims_from_text("Sample text")
        
        assert isinstance(result, list)
        assert len(result) > 0
        mock_llm_instance.extract_claims_from_chunk.assert_called_once()
    
    @patch('hybrid_citation_scraper.claim_extractor.LLMClient')
    @patch('hybrid_citation_scraper.claim_extractor.semantic_chunk_text')
    def test_extract_claims_multiple_chunks(
        self, mock_chunk, mock_llm_client, sample_claim_objects
    ):
        """Test claim extraction from multiple chunks"""
        mock_chunk.return_value = [
            {'chunk_id': 0, 'text': 'Chunk 1', 'start_pos': 0, 'end_pos': 7, 'token_count': 2},
            {'chunk_id': 1, 'text': 'Chunk 2', 'start_pos': 7, 'end_pos': 14, 'token_count': 2}
        ]
        
        mock_llm_instance = mock_llm_client.return_value
        mock_llm_instance.extract_claims_from_chunk.side_effect = [
            [sample_claim_objects[0]],
            [sample_claim_objects[1]]
        ]
        
        extractor = HybridClaimExtractor()
        result = extractor.extract_claims_from_text("Sample text")
        
        assert len(result) == 2
        assert mock_llm_instance.extract_claims_from_chunk.call_count == 2
    
    @patch('hybrid_citation_scraper.claim_extractor.LLMClient')
    @patch('hybrid_citation_scraper.claim_extractor.semantic_chunk_text')
    def test_extract_claims_updates_location(
        self, mock_chunk, mock_llm_client
    ):
        """Test that claim locations are updated with chunk position"""
        mock_chunk.return_value = [
            {'chunk_id': 0, 'text': 'Chunk', 'start_pos': 100, 'end_pos': 105, 'token_count': 1}
        ]
        
        claim = ClaimObject(
            claim_id="test",
            text="Test claim",
            claim_type="qualitative",
            citation_found=False,
            is_original=True,
            location_in_text=LocationInText(start=0, end=10, chunk_id=0)
        )
        
        mock_llm_instance = mock_llm_client.return_value
        mock_llm_instance.extract_claims_from_chunk.return_value = [claim]
        
        extractor = HybridClaimExtractor()
        result = extractor.extract_claims_from_text("Sample text")
        
        # Location should be updated with chunk's start position
        assert result[0].location_in_text.start == 100
        assert result[0].location_in_text.end == 110
    
    @patch('hybrid_citation_scraper.claim_extractor.LLMClient')
    @patch('hybrid_citation_scraper.claim_extractor.semantic_chunk_text')
    def test_extract_claims_with_citations_context(
        self, mock_chunk, mock_llm_client, sample_citations_dict
    ):
        """Test that citations are passed as context"""
        mock_chunk.return_value = [
            {'chunk_id': 0, 'text': 'Chunk', 'start_pos': 0, 'end_pos': 5, 'token_count': 1}
        ]
        
        mock_llm_instance = mock_llm_client.return_value
        mock_llm_instance.extract_claims_from_chunk.return_value = []
        
        extractor = HybridClaimExtractor()
        extractor.citations = sample_citations_dict
        extractor.extract_claims_from_text("Sample text")
        
        # Check that citations were passed
        call_args = mock_llm_instance.extract_claims_from_chunk.call_args
        assert call_args[1]['available_citations'] == sample_citations_dict


class TestMapCitationsToClaims:
    """Tests for map_citations_to_claims method"""
    
    @patch('hybrid_citation_scraper.claim_extractor.LLMClient')
    def test_map_citations_basic(self, mock_llm_client, sample_claim_objects, sample_citations_dict):
        """Test basic citation mapping"""
        extractor = HybridClaimExtractor()
        extractor.claims = sample_claim_objects.copy()
        extractor.citations = sample_citations_dict
        
        result = extractor.map_citations_to_claims()
        
        # Claims with citation_id should have citation_details populated
        for claim in result:
            if claim.citation_id:
                assert claim.citation_details is not None
    
    @patch('hybrid_citation_scraper.claim_extractor.LLMClient')
    def test_map_citations_extracts_id(self, mock_llm_client, sample_citations_dict):
        """Test that citation IDs are extracted from markers"""
        claim = ClaimObject(
            claim_id="test",
            text="Test claim [1]",
            claim_type="qualitative",
            citation_found=True,
            citation_text="[1]",
            is_original=False,
            location_in_text=LocationInText(start=0, end=15, chunk_id=0)
        )
        
        extractor = HybridClaimExtractor()
        extractor.claims = [claim]
        extractor.citations = sample_citations_dict
        
        result = extractor.map_citations_to_claims()
        
        assert result[0].citation_id == "1"
    
    @patch('hybrid_citation_scraper.claim_extractor.LLMClient')
    def test_map_citations_skips_uncited(self, mock_llm_client):
        """Test that claims without citations are skipped"""
        claim = ClaimObject(
            claim_id="test",
            text="Test claim",
            claim_type="qualitative",
            citation_found=False,
            is_original=True,
            location_in_text=LocationInText(start=0, end=10, chunk_id=0)
        )
        
        extractor = HybridClaimExtractor()
        extractor.claims = [claim]
        extractor.citations = {}
        
        result = extractor.map_citations_to_claims()
        
        assert result[0].citation_details is None


class TestSortClaims:
    """Tests for _sort_claims method"""
    
    @patch('hybrid_citation_scraper.claim_extractor.LLMClient')
    def test_sort_claims_by_type_and_citation(self, mock_llm_client, sample_claim_objects):
        """Test claims are sorted by type and citation status"""
        extractor = HybridClaimExtractor()
        extractor.claims = sample_claim_objects.copy()
        
        extractor._sort_claims()
        
        # Should be: qual without citation, quant without citation, 
        # qual with citation, quant with citation
        citations_start_idx = None
        for i, claim in enumerate(extractor.claims):
            if claim.citation_id:
                citations_start_idx = i
                break
        
        if citations_start_idx is not None:
            # Claims before this index should not have citations
            for i in range(citations_start_idx):
                assert not extractor.claims[i].citation_id
    
    @patch('hybrid_citation_scraper.claim_extractor.LLMClient')
    def test_sort_claims_groups_by_citation_id(self, mock_llm_client):
        """Test that claims with same citation_id are grouped"""
        claims = [
            ClaimObject(
                claim_id=f"claim_{i}",
                text=f"Claim {i}",
                claim_type="qualitative",
                citation_found=True,
                citation_id="1",
                citation_text="[1]",
                is_original=False,
                location_in_text=LocationInText(start=0, end=10, chunk_id=0)
            )
            for i in range(3)
        ]
        
        extractor = HybridClaimExtractor()
        extractor.claims = claims
        
        extractor._sort_claims()
        
        # All claims should remain together (same citation_id)
        citation_ids = [c.citation_id for c in extractor.claims if c.citation_id]
        assert len(set(citation_ids)) == 1  # All same citation


class TestGetClaimsByCitation:
    """Tests for get_claims_by_citation method"""
    
    @patch('hybrid_citation_scraper.claim_extractor.LLMClient')
    def test_get_claims_by_citation_groups_correctly(
        self, mock_llm_client, sample_claim_objects
    ):
        """Test that claims are grouped by citation_id"""
        extractor = HybridClaimExtractor()
        extractor.claims = sample_claim_objects.copy()
        
        result = extractor.get_claims_by_citation()
        
        assert isinstance(result, dict)
        assert "_no_citation" in result  # Uncited claims
        
        # Check that claims are grouped by their citation_id
        for citation_id, claims in result.items():
            if citation_id != "_no_citation":
                assert all(c.citation_id == citation_id for c in claims)
    
    @patch('hybrid_citation_scraper.claim_extractor.LLMClient')
    def test_get_claims_by_citation_uncited_group(self, mock_llm_client):
        """Test that uncited claims are grouped together"""
        claims = [
            ClaimObject(
                claim_id="claim_0",
                text="Uncited claim",
                claim_type="qualitative",
                citation_found=False,
                is_original=True,
                location_in_text=LocationInText(start=0, end=13, chunk_id=0)
            )
        ]
        
        extractor = HybridClaimExtractor()
        extractor.claims = claims
        
        result = extractor.get_claims_by_citation()
        
        assert "_no_citation" in result
        assert len(result["_no_citation"]) == 1


class TestSaveResults:
    """Tests for save_results method"""
    
    @patch('hybrid_citation_scraper.claim_extractor.LLMClient')
    def test_save_results_creates_file(
        self, mock_llm_client, sample_claim_objects, 
        sample_citations_dict, tmp_path
    ):
        """Test that results are saved to JSON file"""
        output_path = tmp_path / "results.json"
        
        extractor = HybridClaimExtractor()
        extractor.claims = sample_claim_objects
        extractor.citations = sample_citations_dict
        
        extractor.save_results(str(output_path))
        
        assert output_path.exists()
    
    @patch('hybrid_citation_scraper.claim_extractor.LLMClient')
    def test_save_results_correct_format(
        self, mock_llm_client, sample_claim_objects,
        sample_citations_dict, tmp_path
    ):
        """Test that saved JSON has correct format"""
        output_path = tmp_path / "results.json"
        
        extractor = HybridClaimExtractor()
        extractor.claims = sample_claim_objects
        extractor.citations = sample_citations_dict
        
        extractor.save_results(str(output_path))
        
        with open(output_path, 'r') as f:
            data = json.load(f)
        
        assert 'claims' in data
        assert 'citations' in data
        assert 'summary' in data
        assert data['summary']['total_claims'] == len(sample_claim_objects)


class TestExtractCitationId:
    """Tests for _extract_citation_id static method"""
    
    def test_extract_numeric_citation_id(self):
        """Test extracting numeric citation ID"""
        result = HybridClaimExtractor._extract_citation_id("[1]")
        assert result == "1"
    
    def test_extract_multiple_digit_citation_id(self):
        """Test extracting multi-digit citation ID"""
        result = HybridClaimExtractor._extract_citation_id("[123]")
        assert result == "123"
    
    def test_extract_author_year_citation_id(self):
        """Test extracting author from author-year citation"""
        result = HybridClaimExtractor._extract_citation_id("(Smith, 2020)")
        assert result == "Smith"
    
    def test_extract_fallback_to_stripped(self):
        """Test fallback to stripped marker"""
        result = HybridClaimExtractor._extract_citation_id("CustomMarker")
        assert result == "CustomMarker"


class TestParseCitationDetails:
    """Tests for _parse_citation_details static method"""
    
    def test_parse_citation_extracts_year(self):
        """Test that year is extracted from citation"""
        citation = "Smith, J. (2020). Title of paper. Journal Name, 10(2), 123-145."
        result = HybridClaimExtractor._parse_citation_details(citation)
        
        assert result.year == 2020
    
    def test_parse_citation_extracts_doi(self):
        """Test that DOI is extracted from citation"""
        citation = "Smith, J. (2020). Title. Journal. doi: 10.1234/test.456"
        result = HybridClaimExtractor._parse_citation_details(citation)
        
        assert result.doi == "10.1234/test.456"
    
    def test_parse_citation_extracts_url(self):
        """Test that URL is extracted from citation"""
        citation = "Smith, J. (2020). Title. https://example.com/paper"
        result = HybridClaimExtractor._parse_citation_details(citation)
        
        assert result.url == "https://example.com/paper"
    
    def test_parse_citation_extracts_author(self):
        """Test that author is extracted from citation"""
        citation = "Smith, J. (2020). Title of paper. Journal."
        result = HybridClaimExtractor._parse_citation_details(citation)
        
        assert result.authors is not None
        assert len(result.authors) > 0
    
    def test_parse_citation_stores_raw_text(self):
        """Test that raw citation text is stored"""
        citation = "Smith, J. (2020). Title."
        result = HybridClaimExtractor._parse_citation_details(citation)
        
        assert result.raw_text == citation
    
    def test_parse_citation_handles_missing_fields(self):
        """Test parsing citation with missing fields"""
        citation = "Incomplete citation without standard format"
        result = HybridClaimExtractor._parse_citation_details(citation)
        
        # Should not crash, should store raw text
        assert isinstance(result, CitationDetails)
        assert result.raw_text == citation


class TestProcessPDF:
    """Tests for process_pdf method (integration test)"""
    
    @patch('hybrid_citation_scraper.claim_extractor.LLMClient')
    @patch('hybrid_citation_scraper.claim_extractor.extract_text_from_pdf')
    @patch('hybrid_citation_scraper.claim_extractor.extract_title_and_abstract')
    @patch('hybrid_citation_scraper.claim_extractor.locate_reference_section')
    @patch('hybrid_citation_scraper.claim_extractor.detect_citation_style')
    @patch('hybrid_citation_scraper.claim_extractor.parse_citations_deterministic')
    @patch('hybrid_citation_scraper.claim_extractor.validate_citations')
    @patch('hybrid_citation_scraper.claim_extractor.semantic_chunk_text')
    def test_process_pdf_complete_pipeline(
        self, mock_chunk, mock_validate, mock_parse, mock_detect,
        mock_locate, mock_extract_title, mock_extract_text, mock_llm_client,
        sample_pdf_text, sample_references_section, sample_citations_dict
    ):
        """Test complete PDF processing pipeline"""
        # Setup all mocks
        mock_extract_text.return_value = sample_pdf_text
        mock_extract_title.return_value = {
            'title': 'Test Paper',
            'abstract': 'Test abstract'
        }
        mock_locate.return_value = sample_references_section
        mock_detect.return_value = 'numeric'
        mock_parse.return_value = sample_citations_dict
        mock_validate.return_value = True
        mock_chunk.return_value = [
            {'chunk_id': 0, 'text': 'Test', 'start_pos': 0, 'end_pos': 4, 'token_count': 1}
        ]
        
        mock_llm_instance = mock_llm_client.return_value
        mock_llm_instance.extract_claims_from_chunk.return_value = []
        mock_llm_instance.get_cost_summary.return_value = {
            'input_tokens': 100,
            'output_tokens': 50,
            'total_cost': 0.01
        }
        
        extractor = HybridClaimExtractor()
        claims, citations = extractor.process_pdf("test.pdf")
        
        assert isinstance(claims, list)
        assert isinstance(citations, dict)
        assert extractor.paper_title == 'Test Paper'
        assert extractor.paper_abstract == 'Test abstract'
