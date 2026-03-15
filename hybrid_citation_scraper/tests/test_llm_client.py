"""Tests for hybrid_citation_scraper.llm_client module"""

import pytest
import json
from unittest.mock import Mock, patch, MagicMock
from hybrid_citation_scraper.llm_client import LLMClient
from models import ClaimObject, LocationInText


class TestLLMClientInit:
    """Tests for LLMClient initialization"""
    
    @patch('hybrid_citation_scraper.llm_client.OpenAI')
    def test_init_creates_client(self, mock_openai):
        """Test that LLMClient initializes OpenAI client"""
        client = LLMClient()
        assert mock_openai.called
        assert hasattr(client, 'client')
        assert hasattr(client, 'model')
    
    @patch('hybrid_citation_scraper.llm_client.OpenAI')
    def test_init_sets_token_counters(self, mock_openai):
        """Test that token counters are initialized"""
        client = LLMClient()
        assert client.total_input_tokens == 0
        assert client.total_output_tokens == 0
    
    @patch('hybrid_citation_scraper.llm_client.OpenAI')
    def test_init_uses_config_model(self, mock_openai):
        """Test that configured model is used"""
        client = LLMClient()
        from hybrid_citation_scraper.config import CLAIM_EXTRACTION_MODEL
        assert client.model == CLAIM_EXTRACTION_MODEL


class TestExtractClaimsFromChunk:
    """Tests for extract_claims_from_chunk method"""
    
    @patch('hybrid_citation_scraper.llm_client.OpenAI')
    def test_extract_claims_basic(self, mock_openai, sample_claims_data):
        """Test basic claim extraction from chunk"""
        # Setup mock
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = json.dumps({"claims": sample_claims_data})
        mock_response.usage = Mock()
        mock_response.usage.prompt_tokens = 100
        mock_response.usage.completion_tokens = 50
        
        mock_openai.return_value.chat.completions.create.return_value = mock_response
        
        client = LLMClient()
        result = client.extract_claims_from_chunk("Sample text", chunk_id=0)
        
        assert isinstance(result, list)
        assert len(result) == len(sample_claims_data)
        assert all(isinstance(claim, ClaimObject) for claim in result)
    
    @patch('hybrid_citation_scraper.llm_client.OpenAI')
    def test_extract_claims_with_citations_context(self, mock_openai, sample_citations_dict):
        """Test claim extraction with citation context"""
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = json.dumps({"claims": []})
        mock_response.usage = Mock()
        mock_response.usage.prompt_tokens = 100
        mock_response.usage.completion_tokens = 50
        
        mock_openai.return_value.chat.completions.create.return_value = mock_response
        
        client = LLMClient()
        result = client.extract_claims_from_chunk(
            "Sample text",
            chunk_id=0,
            available_citations=sample_citations_dict
        )
        
        # Check that create was called with citations in context
        call_args = mock_openai.return_value.chat.completions.create.call_args
        prompt = call_args[1]['messages'][1]['content']
        assert 'Available citations' in prompt
    
    @patch('hybrid_citation_scraper.llm_client.OpenAI')
    def test_extract_claims_with_paper_context(self, mock_openai):
        """Test claim extraction with paper title and abstract"""
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = json.dumps({"claims": []})
        mock_response.usage = Mock()
        mock_response.usage.prompt_tokens = 100
        mock_response.usage.completion_tokens = 50
        
        mock_openai.return_value.chat.completions.create.return_value = mock_response
        
        client = LLMClient()
        result = client.extract_claims_from_chunk(
            "Sample text",
            chunk_id=0,
            paper_title="Test Paper",
            paper_abstract="This is the abstract"
        )
        
        call_args = mock_openai.return_value.chat.completions.create.call_args
        prompt = call_args[1]['messages'][1]['content']
        assert 'Paper Context' in prompt
        assert 'Test Paper' in prompt
    
    @patch('hybrid_citation_scraper.llm_client.OpenAI')
    def test_extract_claims_tracks_tokens(self, mock_openai):
        """Test that token usage is tracked"""
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = json.dumps({"claims": []})
        mock_response.usage = Mock()
        mock_response.usage.prompt_tokens = 123
        mock_response.usage.completion_tokens = 456
        
        mock_openai.return_value.chat.completions.create.return_value = mock_response
        
        client = LLMClient()
        client.extract_claims_from_chunk("Sample text", chunk_id=0)
        
        assert client.total_input_tokens == 123
        assert client.total_output_tokens == 456
    
    @patch('hybrid_citation_scraper.llm_client.OpenAI')
    def test_extract_claims_handles_direct_array_format(self, mock_openai, sample_claims_data):
        """Test handling of direct array response format"""
        mock_response = Mock()
        mock_response.choices = [Mock()]
        # Direct array format without wrapper
        mock_response.choices[0].message.content = json.dumps(sample_claims_data)
        mock_response.usage = Mock()
        mock_response.usage.prompt_tokens = 100
        mock_response.usage.completion_tokens = 50
        
        mock_openai.return_value.chat.completions.create.return_value = mock_response
        
        client = LLMClient()
        result = client.extract_claims_from_chunk("Sample text", chunk_id=0)
        
        assert len(result) == len(sample_claims_data)
    
    @patch('hybrid_citation_scraper.llm_client.OpenAI')
    def test_extract_claims_error_handling(self, mock_openai):
        """Test error handling when LLM call fails"""
        mock_openai.return_value.chat.completions.create.side_effect = Exception("API Error")
        
        client = LLMClient()
        result = client.extract_claims_from_chunk("Sample text", chunk_id=0)
        
        assert result == []
    
    @patch('hybrid_citation_scraper.llm_client.OpenAI')
    def test_extract_claims_empty_response(self, mock_openai):
        """Test handling of empty LLM response"""
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = None
        mock_response.usage = Mock()
        mock_response.usage.prompt_tokens = 100
        mock_response.usage.completion_tokens = 0
        
        mock_openai.return_value.chat.completions.create.return_value = mock_response
        
        client = LLMClient()
        result = client.extract_claims_from_chunk("Sample text", chunk_id=0)
        
        assert result == []
    
    @patch('hybrid_citation_scraper.llm_client.OpenAI')
    def test_extract_claims_sets_location(self, mock_openai, sample_claims_data):
        """Test that location information is set for claims"""
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = json.dumps(sample_claims_data)
        mock_response.usage = Mock()
        mock_response.usage.prompt_tokens = 100
        mock_response.usage.completion_tokens = 50
        
        mock_openai.return_value.chat.completions.create.return_value = mock_response
        
        client = LLMClient()
        result = client.extract_claims_from_chunk("Sample text", chunk_id=5)
        
        for claim in result:
            assert claim.location_in_text is not None
            assert claim.location_in_text.chunk_id == 5


class TestParseReferencesWithLLM:
    """Tests for parse_references_with_llm method"""
    
    @patch('hybrid_citation_scraper.llm_client.OpenAI')
    def test_parse_references_basic(self, mock_openai, sample_citations_dict):
        """Test basic reference parsing"""
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = json.dumps(sample_citations_dict)
        mock_response.usage = Mock()
        mock_response.usage.prompt_tokens = 200
        mock_response.usage.completion_tokens = 300
        
        mock_openai.return_value.chat.completions.create.return_value = mock_response
        
        client = LLMClient()
        result = client.parse_references_with_llm("References section text")
        
        assert isinstance(result, dict)
        assert len(result) == len(sample_citations_dict)
        assert "1" in result
    
    @patch('hybrid_citation_scraper.llm_client.OpenAI')
    def test_parse_references_wrapped_format(self, mock_openai, sample_citations_dict):
        """Test parsing with wrapped citations format"""
        mock_response = Mock()
        mock_response.choices = [Mock()]
        wrapped_response = {"citations": sample_citations_dict}
        mock_response.choices[0].message.content = json.dumps(wrapped_response)
        mock_response.usage = Mock()
        mock_response.usage.prompt_tokens = 200
        mock_response.usage.completion_tokens = 300
        
        mock_openai.return_value.chat.completions.create.return_value = mock_response
        
        client = LLMClient()
        result = client.parse_references_with_llm("References section text")
        
        assert result == sample_citations_dict
    
    @patch('hybrid_citation_scraper.llm_client.OpenAI')
    def test_parse_references_tracks_tokens(self, mock_openai):
        """Test that token usage is tracked"""
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = json.dumps({})
        mock_response.usage = Mock()
        mock_response.usage.prompt_tokens = 234
        mock_response.usage.completion_tokens = 567
        
        mock_openai.return_value.chat.completions.create.return_value = mock_response
        
        client = LLMClient()
        client.parse_references_with_llm("References text")
        
        assert client.total_input_tokens == 234
        assert client.total_output_tokens == 567
    
    @patch('hybrid_citation_scraper.llm_client.OpenAI')
    def test_parse_references_error_handling(self, mock_openai):
        """Test error handling when parsing fails"""
        mock_openai.return_value.chat.completions.create.side_effect = Exception("API Error")
        
        client = LLMClient()
        result = client.parse_references_with_llm("References text")
        
        assert result == {}
    
    @patch('hybrid_citation_scraper.llm_client.OpenAI')
    def test_parse_references_empty_response(self, mock_openai):
        """Test handling of empty response"""
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = None
        mock_response.usage = Mock()
        mock_response.usage.prompt_tokens = 100
        mock_response.usage.completion_tokens = 0
        
        mock_openai.return_value.chat.completions.create.return_value = mock_response
        
        client = LLMClient()
        result = client.parse_references_with_llm("References text")
        
        assert result == {}


class TestCallLLM:
    """Tests for generic call_llm method"""
    
    @patch('hybrid_citation_scraper.llm_client.OpenAI')
    def test_call_llm_json_format(self, mock_openai):
        """Test LLM call with JSON response format"""
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = json.dumps({"result": "success"})
        mock_response.usage = Mock()
        mock_response.usage.prompt_tokens = 50
        mock_response.usage.completion_tokens = 30
        
        mock_openai.return_value.chat.completions.create.return_value = mock_response
        
        client = LLMClient()
        result = client.call_llm("Test prompt", response_format="json")
        
        assert isinstance(result, dict)
        assert result["result"] == "success"
    
    @patch('hybrid_citation_scraper.llm_client.OpenAI')
    def test_call_llm_text_format(self, mock_openai):
        """Test LLM call with text response format"""
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = "Plain text response"
        mock_response.usage = Mock()
        mock_response.usage.prompt_tokens = 50
        mock_response.usage.completion_tokens = 30
        
        mock_openai.return_value.chat.completions.create.return_value = mock_response
        
        client = LLMClient()
        result = client.call_llm("Test prompt", response_format="text")
        
        assert isinstance(result, str)
        assert result == "Plain text response"
    
    @patch('hybrid_citation_scraper.llm_client.OpenAI')
    def test_call_llm_tracks_tokens(self, mock_openai):
        """Test that token usage is tracked"""
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = "Response"
        mock_response.usage = Mock()
        mock_response.usage.prompt_tokens = 111
        mock_response.usage.completion_tokens = 222
        
        mock_openai.return_value.chat.completions.create.return_value = mock_response
        
        client = LLMClient()
        client.call_llm("Test prompt", response_format="text")
        
        assert client.total_input_tokens == 111
        assert client.total_output_tokens == 222
    
    @patch('hybrid_citation_scraper.llm_client.OpenAI')
    def test_call_llm_error_handling_json(self, mock_openai):
        """Test error handling for JSON format"""
        mock_openai.return_value.chat.completions.create.side_effect = Exception("API Error")
        
        client = LLMClient()
        result = client.call_llm("Test prompt", response_format="json")
        
        assert result == {}
    
    @patch('hybrid_citation_scraper.llm_client.OpenAI')
    def test_call_llm_error_handling_text(self, mock_openai):
        """Test error handling for text format"""
        mock_openai.return_value.chat.completions.create.side_effect = Exception("API Error")
        
        client = LLMClient()
        result = client.call_llm("Test prompt", response_format="text")
        
        assert result == ""
    
    @patch('hybrid_citation_scraper.llm_client.OpenAI')
    def test_call_llm_empty_json_response(self, mock_openai):
        """Test handling of empty JSON response"""
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = None
        mock_response.usage = Mock()
        mock_response.usage.prompt_tokens = 50
        mock_response.usage.completion_tokens = 0
        
        mock_openai.return_value.chat.completions.create.return_value = mock_response
        
        client = LLMClient()
        result = client.call_llm("Test prompt", response_format="json")
        
        assert result == {}
    
    @patch('hybrid_citation_scraper.llm_client.OpenAI')
    def test_call_llm_empty_text_response(self, mock_openai):
        """Test handling of empty text response"""
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = None
        mock_response.usage = Mock()
        mock_response.usage.prompt_tokens = 50
        mock_response.usage.completion_tokens = 0
        
        mock_openai.return_value.chat.completions.create.return_value = mock_response
        
        client = LLMClient()
        result = client.call_llm("Test prompt", response_format="text")
        
        assert result == ""


class TestGetCostSummary:
    """Tests for get_cost_summary method"""
    
    @patch('hybrid_citation_scraper.llm_client.OpenAI')
    def test_cost_summary_initial_state(self, mock_openai):
        """Test cost summary with no API calls"""
        client = LLMClient()
        summary = client.get_cost_summary()
        
        assert summary['input_tokens'] == 0
        assert summary['output_tokens'] == 0
        assert summary['total_tokens'] == 0
        assert summary['input_cost'] == 0.0
        assert summary['output_cost'] == 0.0
        assert summary['total_cost'] == 0.0
    
    @patch('hybrid_citation_scraper.llm_client.OpenAI')
    def test_cost_summary_after_api_calls(self, mock_openai):
        """Test cost summary after making API calls"""
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = json.dumps({})
        mock_response.usage = Mock()
        mock_response.usage.prompt_tokens = 1000
        mock_response.usage.completion_tokens = 500
        
        mock_openai.return_value.chat.completions.create.return_value = mock_response
        
        client = LLMClient()
        client.extract_claims_from_chunk("Test text", chunk_id=0)
        
        summary = client.get_cost_summary()
        
        assert summary['input_tokens'] == 1000
        assert summary['output_tokens'] == 500
        assert summary['total_tokens'] == 1500
        assert summary['input_cost'] > 0
        assert summary['output_cost'] > 0
        assert summary['total_cost'] == summary['input_cost'] + summary['output_cost']
    
    @patch('hybrid_citation_scraper.llm_client.OpenAI')
    def test_cost_calculation_accuracy(self, mock_openai):
        """Test that cost calculation uses correct pricing"""
        # GPT-4o-mini: $0.150/M input, $0.600/M output
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = json.dumps({})
        mock_response.usage = Mock()
        mock_response.usage.prompt_tokens = 1_000_000  # 1M tokens
        mock_response.usage.completion_tokens = 1_000_000  # 1M tokens
        
        mock_openai.return_value.chat.completions.create.return_value = mock_response
        
        client = LLMClient()
        client.extract_claims_from_chunk("Test text", chunk_id=0)
        
        summary = client.get_cost_summary()
        
        # Should be $0.150 for input and $0.600 for output
        assert abs(summary['input_cost'] - 0.150) < 0.001
        assert abs(summary['output_cost'] - 0.600) < 0.001
        assert abs(summary['total_cost'] - 0.750) < 0.001
    
    @patch('hybrid_citation_scraper.llm_client.OpenAI')
    def test_cost_summary_accumulates(self, mock_openai):
        """Test that costs accumulate across multiple calls"""
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = json.dumps({})
        mock_response.usage = Mock()
        mock_response.usage.prompt_tokens = 100
        mock_response.usage.completion_tokens = 50
        
        mock_openai.return_value.chat.completions.create.return_value = mock_response
        
        client = LLMClient()
        client.call_llm("First call", response_format="json")
        client.call_llm("Second call", response_format="json")
        
        summary = client.get_cost_summary()
        
        # Should accumulate from both calls
        assert summary['input_tokens'] == 200
        assert summary['output_tokens'] == 100
        assert summary['total_tokens'] == 300
