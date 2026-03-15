"""Integration tests for hybrid_citation_scraper complete workflows"""

import pytest
from unittest.mock import Mock, patch
from pathlib import Path
import json

from hybrid_citation_scraper.claim_extractor import HybridClaimExtractor
from models import ClaimObject


@pytest.mark.integration
class TestCompletePipeline:
    """Integration tests for complete processing pipeline"""
    
    @patch('hybrid_citation_scraper.claim_extractor.LLMClient')
    @patch('hybrid_citation_scraper.claim_extractor.extract_text_from_pdf')
    @patch('hybrid_citation_scraper.claim_extractor.extract_title_and_abstract')
    @patch('hybrid_citation_scraper.claim_extractor.locate_reference_section')
    @patch('hybrid_citation_scraper.claim_extractor.detect_citation_style')
    @patch('hybrid_citation_scraper.claim_extractor.parse_citations_deterministic')
    @patch('hybrid_citation_scraper.claim_extractor.validate_citations')
    @patch('hybrid_citation_scraper.claim_extractor.semantic_chunk_text')
    def test_end_to_end_deterministic_pipeline(
        self, mock_chunk, mock_validate, mock_parse, mock_detect,
        mock_locate, mock_extract_title, mock_extract_text, mock_llm_client,
        sample_pdf_text, sample_references_section, sample_citations_dict,
        sample_claims_data
    ):
        """Test complete end-to-end pipeline with deterministic parsing"""
        # Setup mocks for successful deterministic path
        mock_extract_text.return_value = sample_pdf_text
        mock_extract_title.return_value = {
            'title': 'Machine Learning for Climate Prediction',
            'abstract': 'This paper presents a novel approach to climate prediction.'
        }
        mock_locate.return_value = sample_references_section
        mock_detect.return_value = 'numeric'
        mock_parse.return_value = sample_citations_dict
        mock_validate.return_value = True
        mock_chunk.return_value = [
            {
                'chunk_id': 0,
                'text': 'We achieve 95% accuracy [1]. Climate change is critical [2].',
                'start_pos': 0,
                'end_pos': 61,
                'token_count': 15
            }
        ]
        
        # Setup LLM mock
        mock_llm_instance = mock_llm_client.return_value
        mock_llm_instance.extract_claims_from_chunk.return_value = [
            ClaimObject(
                claim_id="claim_0_0",
                text="We achieve 95% accuracy",
                claim_type="quantitative",
                citation_found=True,
                citation_text="[1]",
                is_original=False
            ),
            ClaimObject(
                claim_id="claim_0_1",
                text="Climate change is critical",
                claim_type="qualitative",
                citation_found=True,
                citation_text="[2]",
                is_original=False
            )
        ]
        mock_llm_instance.get_cost_summary.return_value = {
            'input_tokens': 500,
            'output_tokens': 200,
            'total_cost': 0.05
        }
        
        # Run pipeline
        extractor = HybridClaimExtractor()
        claims, citations = extractor.process_pdf("test.pdf")
        
        # Verify results
        assert len(claims) > 0
        assert len(citations) > 0
        assert extractor.paper_title is not None
        assert extractor.paper_abstract is not None
        
        # Verify deterministic path was used
        mock_parse.assert_called_once()
        mock_validate.assert_called_once()
    
    @patch('hybrid_citation_scraper.claim_extractor.LLMClient')
    @patch('hybrid_citation_scraper.claim_extractor.extract_text_from_pdf')
    @patch('hybrid_citation_scraper.claim_extractor.extract_title_and_abstract')
    @patch('hybrid_citation_scraper.claim_extractor.locate_reference_section')
    @patch('hybrid_citation_scraper.claim_extractor.semantic_chunk_text')
    def test_end_to_end_llm_fallback_pipeline(
        self, mock_chunk, mock_locate, mock_extract_title,
        mock_extract_text, mock_llm_client, sample_pdf_text
    ):
        """Test complete pipeline with LLM fallback"""
        # Setup mocks for LLM fallback path
        mock_extract_text.return_value = sample_pdf_text
        mock_extract_title.return_value = {
            'title': 'Test Paper',
            'abstract': 'Abstract text'
        }
        mock_locate.return_value = None  # Force LLM fallback
        mock_chunk.return_value = [
            {'chunk_id': 0, 'text': 'Test text', 'start_pos': 0, 'end_pos': 9, 'token_count': 2}
        ]
        
        # Setup LLM mock
        mock_llm_instance = mock_llm_client.return_value
        mock_llm_instance.parse_references_with_llm.return_value = {
            "1": "LLM-parsed citation"
        }
        mock_llm_instance.extract_claims_from_chunk.return_value = []
        mock_llm_instance.get_cost_summary.return_value = {
            'input_tokens': 1000,
            'output_tokens': 500,
            'total_cost': 0.10
        }
        
        # Run pipeline
        extractor = HybridClaimExtractor()
        claims, citations = extractor.process_pdf("test.pdf")
        
        # Verify LLM fallback was used
        mock_llm_instance.parse_references_with_llm.assert_called_once()
        assert "1" in citations


@pytest.mark.integration
class TestClaimGrouping:
    """Integration tests for claim grouping and sorting"""
    
    @patch('hybrid_citation_scraper.claim_extractor.LLMClient')
    def test_claims_grouped_by_citation(self, mock_llm_client):
        """Test that claims are properly grouped by citation"""
        extractor = HybridClaimExtractor()
        extractor.claims = [
            ClaimObject(
                claim_id="claim_0",
                text="Claim with citation 1",
                claim_type="quantitative",
                citation_found=True,
                citation_id="1",
                citation_text="[1]",
                is_original=False
            ),
            ClaimObject(
                claim_id="claim_1",
                text="Another claim with citation 1",
                claim_type="qualitative",
                citation_found=True,
                citation_id="1",
                citation_text="[1]",
                is_original=False
            ),
            ClaimObject(
                claim_id="claim_2",
                text="Claim without citation",
                claim_type="qualitative",
                citation_found=False,
                is_original=True
            ),
            ClaimObject(
                claim_id="claim_3",
                text="Claim with citation 2",
                claim_type="quantitative",
                citation_found=True,
                citation_id="2",
                citation_text="[2]",
                is_original=False
            )
        ]
        
        grouped = extractor.get_claims_by_citation()
        
        # Verify grouping
        assert "1" in grouped
        assert "2" in grouped
        assert "_no_citation" in grouped
        
        assert len(grouped["1"]) == 2
        assert len(grouped["2"]) == 1
        assert len(grouped["_no_citation"]) == 1
    
    @patch('hybrid_citation_scraper.claim_extractor.LLMClient')
    def test_claims_sorted_correctly(self, mock_llm_client):
        """Test that claims are sorted by type and citation status"""
        extractor = HybridClaimExtractor()
        extractor.claims = [
            ClaimObject(
                claim_id="claim_0",
                text="Quantitative with citation",
                claim_type="quantitative",
                citation_found=True,
                citation_id="1",
                citation_text="[1]",
                is_original=False
            ),
            ClaimObject(
                claim_id="claim_1",
                text="Qualitative without citation",
                claim_type="qualitative",
                citation_found=False,
                is_original=True
            ),
            ClaimObject(
                claim_id="claim_2",
                text="Quantitative without citation",
                claim_type="quantitative",
                citation_found=False,
                is_original=True
            ),
            ClaimObject(
                claim_id="claim_3",
                text="Qualitative with citation",
                claim_type="qualitative",
                citation_found=True,
                citation_id="2",
                citation_text="[2]",
                is_original=False
            )
        ]
        
        extractor._sort_claims()
        
        # Expected order:
        # 1. Qualitative without citation
        # 2. Quantitative without citation
        # 3. Qualitative with citation
        # 4. Quantitative with citation
        
        sorted_claims = extractor.claims
        
        # Find index where citations start
        citation_start = None
        for i, claim in enumerate(sorted_claims):
            if claim.citation_id:
                citation_start = i
                break
        
        # All claims before citation_start should have no citation
        if citation_start is not None:
            for i in range(citation_start):
                assert not sorted_claims[i].citation_id


@pytest.mark.integration
class TestResultsSaving:
    """Integration tests for saving and loading results"""
    
    @patch('hybrid_citation_scraper.claim_extractor.LLMClient')
    def test_save_and_verify_json_format(
        self, mock_llm_client, tmp_path, sample_claim_objects, sample_citations_dict
    ):
        """Test saving results and verify JSON structure"""
        output_file = tmp_path / "test_results.json"
        
        extractor = HybridClaimExtractor()
        extractor.claims = sample_claim_objects
        extractor.citations = sample_citations_dict
        
        extractor.save_results(str(output_file))
        
        # Verify file exists
        assert output_file.exists()
        
        # Load and verify structure
        with open(output_file, 'r') as f:
            data = json.load(f)
        
        assert 'claims' in data
        assert 'citations' in data
        assert 'summary' in data
        
        # Verify summary
        assert data['summary']['total_claims'] == len(sample_claim_objects)
        assert 'quantitative_claims' in data['summary']
        assert 'qualitative_claims' in data['summary']
        assert 'claims_with_citations' in data['summary']
        
        # Verify claims data
        assert len(data['claims']) == len(sample_claim_objects)
        for claim_data in data['claims']:
            assert 'claim_id' in claim_data
            assert 'text' in claim_data
            assert 'claim_type' in claim_data
        
        # Verify citations data
        assert data['citations'] == sample_citations_dict


@pytest.mark.integration
class TestErrorRecovery:
    """Integration tests for error handling and recovery"""
    
    @patch('hybrid_citation_scraper.claim_extractor.LLMClient')
    @patch('hybrid_citation_scraper.claim_extractor.extract_text_from_pdf')
    def test_handles_pdf_extraction_error(self, mock_extract_text, mock_llm_client):
        """Test graceful handling of PDF extraction errors"""
        mock_extract_text.side_effect = Exception("PDF read error")
        
        extractor = HybridClaimExtractor()
        
        with pytest.raises(Exception):
            extractor.extract_citations("bad.pdf")
    
    @patch('hybrid_citation_scraper.claim_extractor.LLMClient')
    @patch('hybrid_citation_scraper.claim_extractor.extract_text_from_pdf')
    @patch('hybrid_citation_scraper.claim_extractor.locate_reference_section')
    @patch('hybrid_citation_scraper.claim_extractor.detect_citation_style')
    @patch('hybrid_citation_scraper.claim_extractor.parse_citations_deterministic')
    def test_recovers_from_parsing_error(
        self, mock_parse, mock_detect, mock_locate,
        mock_extract_text, mock_llm_client, sample_pdf_text
    ):
        """Test recovery from parsing errors via LLM fallback"""
        mock_extract_text.return_value = sample_pdf_text
        mock_locate.return_value = "References section"
        mock_detect.return_value = 'numeric'
        mock_parse.side_effect = Exception("Parsing error")
        
        mock_llm_instance = mock_llm_client.return_value
        mock_llm_instance.parse_references_with_llm.return_value = {"1": "Fallback citation"}
        
        extractor = HybridClaimExtractor()
        result = extractor.extract_citations("test.pdf")
        
        # Should have fallen back to LLM
        assert "1" in result
        mock_llm_instance.parse_references_with_llm.assert_called_once()


@pytest.mark.integration
@pytest.mark.slow
class TestLargeDocuments:
    """Integration tests for processing large documents"""
    
    @patch('hybrid_citation_scraper.claim_extractor.LLMClient')
    @patch('hybrid_citation_scraper.claim_extractor.extract_text_from_pdf')
    @patch('hybrid_citation_scraper.claim_extractor.extract_title_and_abstract')
    @patch('hybrid_citation_scraper.claim_extractor.locate_reference_section')
    @patch('hybrid_citation_scraper.claim_extractor.detect_citation_style')
    @patch('hybrid_citation_scraper.claim_extractor.parse_citations_deterministic')
    @patch('hybrid_citation_scraper.claim_extractor.validate_citations')
    @patch('hybrid_citation_scraper.claim_extractor.semantic_chunk_text')
    def test_processes_large_document(
        self, mock_chunk, mock_validate, mock_parse, mock_detect,
        mock_locate, mock_extract_title, mock_extract_text, mock_llm_client
    ):
        """Test processing document with many chunks"""
        # Create large document text
        large_text = "This is a sentence. " * 1000
        
        mock_extract_text.return_value = large_text
        mock_extract_title.return_value = {'title': 'Large Doc', 'abstract': 'Abstract'}
        mock_locate.return_value = "References"
        mock_detect.return_value = 'numeric'
        mock_parse.return_value = {"1": "Citation"}
        mock_validate.return_value = True
        
        # Simulate many chunks
        mock_chunk.return_value = [
            {
                'chunk_id': i,
                'text': f'Chunk {i}',
                'start_pos': i * 10,
                'end_pos': (i + 1) * 10,
                'token_count': 2
            }
            for i in range(20)  # 20 chunks
        ]
        
        mock_llm_instance = mock_llm_client.return_value
        mock_llm_instance.extract_claims_from_chunk.return_value = []
        mock_llm_instance.get_cost_summary.return_value = {
            'input_tokens': 10000,
            'output_tokens': 2000,
            'total_cost': 1.50
        }
        
        extractor = HybridClaimExtractor()
        claims, citations = extractor.process_pdf("large.pdf")
        
        # Verify all chunks were processed
        assert mock_llm_instance.extract_claims_from_chunk.call_count == 20
