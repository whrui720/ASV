"""Tests for asv.extraction.llm_client module.

The client wraps the Gemini API (`google.genai`). Tests patch
`asv.extraction.llm_client.genai` so `genai.Client(...)` returns a mock whose
`.models.generate_content(...)` yields a fake response with `.text` and
`.usage_metadata` (Gemini's token-count shape).
"""

import pytest
import json
from unittest.mock import Mock, patch
from asv.extraction.llm_client import LLMClient
from asv.core.models import ClaimObject, LocationInText


def _make_response(text, prompt_tokens=100, candidate_tokens=50):
    """Build a fake Gemini `generate_content` response."""
    resp = Mock()
    resp.text = text
    usage = Mock()
    usage.prompt_token_count = prompt_tokens
    usage.candidates_token_count = candidate_tokens
    resp.usage_metadata = usage
    return resp


def _set_response(mock_genai, text, prompt_tokens=100, candidate_tokens=50):
    """Wire the patched genai so generate_content returns our fake response."""
    resp = _make_response(text, prompt_tokens, candidate_tokens)
    mock_genai.Client.return_value.models.generate_content.return_value = resp
    return resp


def _set_error(mock_genai, exc):
    """Wire generate_content to raise (a non-transient error, so no retry/sleep)."""
    mock_genai.Client.return_value.models.generate_content.side_effect = exc


def _sent_prompt(mock_genai):
    """The prompt string passed as `contents=` to generate_content."""
    call = mock_genai.Client.return_value.models.generate_content.call_args
    return call.kwargs["contents"]


class TestLLMClientInit:
    """Tests for LLMClient initialization"""

    @patch('asv.extraction.llm_client.genai')
    def test_init_creates_client(self, mock_genai):
        """Test that LLMClient initializes the Gemini client"""
        client = LLMClient()
        assert mock_genai.Client.called
        assert hasattr(client, 'client')
        assert hasattr(client, 'model')

    @patch('asv.extraction.llm_client.genai')
    def test_init_sets_token_counters(self, mock_genai):
        """Test that token counters are initialized"""
        client = LLMClient()
        assert client.total_input_tokens == 0
        assert client.total_output_tokens == 0

    @patch('asv.extraction.llm_client.genai')
    def test_init_uses_config_model(self, mock_genai):
        """Test that configured model is used"""
        client = LLMClient()
        from asv.core.llm_config import DEFAULT_LLM_MODEL
        assert client.model == DEFAULT_LLM_MODEL


class TestExtractClaimsFromChunk:
    """Tests for extract_claims_from_chunk method"""

    @patch('asv.extraction.llm_client.genai')
    def test_extract_claims_basic(self, mock_genai, sample_claims_data):
        """Test basic claim extraction from chunk"""
        _set_response(mock_genai, json.dumps({"claims": sample_claims_data}))

        client = LLMClient()
        result = client.extract_claims_from_chunk("Sample text", chunk_id=0)

        assert isinstance(result, list)
        assert len(result) == len(sample_claims_data)
        assert all(isinstance(claim, ClaimObject) for claim in result)

    @patch('asv.extraction.llm_client.genai')
    def test_extract_claims_with_citations_context(self, mock_genai, sample_citations_dict):
        """Test claim extraction with citation context"""
        _set_response(mock_genai, json.dumps({"claims": []}))

        client = LLMClient()
        client.extract_claims_from_chunk(
            "Sample text",
            chunk_id=0,
            available_citations=sample_citations_dict
        )

        assert 'Available citations' in _sent_prompt(mock_genai)

    @patch('asv.extraction.llm_client.genai')
    def test_extract_claims_with_paper_context(self, mock_genai):
        """Test claim extraction with paper title and abstract"""
        _set_response(mock_genai, json.dumps({"claims": []}))

        client = LLMClient()
        client.extract_claims_from_chunk(
            "Sample text",
            chunk_id=0,
            paper_title="Test Paper",
            paper_abstract="This is the abstract"
        )

        prompt = _sent_prompt(mock_genai)
        assert 'Paper Context' in prompt
        assert 'Test Paper' in prompt

    @patch('asv.extraction.llm_client.genai')
    def test_extract_claims_tracks_tokens(self, mock_genai):
        """Test that token usage is tracked"""
        _set_response(mock_genai, json.dumps({"claims": []}), prompt_tokens=123, candidate_tokens=456)

        client = LLMClient()
        client.extract_claims_from_chunk("Sample text", chunk_id=0)

        assert client.total_input_tokens == 123
        assert client.total_output_tokens == 456

    @patch('asv.extraction.llm_client.genai')
    def test_extract_claims_handles_direct_array_format(self, mock_genai, sample_claims_data):
        """Test handling of direct array response format"""
        _set_response(mock_genai, json.dumps(sample_claims_data))

        client = LLMClient()
        result = client.extract_claims_from_chunk("Sample text", chunk_id=0)

        assert len(result) == len(sample_claims_data)

    @patch('asv.extraction.llm_client.genai')
    def test_extract_claims_error_handling(self, mock_genai):
        """Test error handling when LLM call fails"""
        _set_error(mock_genai, Exception("API Error"))

        client = LLMClient()
        result = client.extract_claims_from_chunk("Sample text", chunk_id=0)

        assert result == []

    @patch('asv.extraction.llm_client.genai')
    def test_extract_claims_empty_response(self, mock_genai):
        """Test handling of empty LLM response"""
        _set_response(mock_genai, None, candidate_tokens=0)

        client = LLMClient()
        result = client.extract_claims_from_chunk("Sample text", chunk_id=0)

        assert result == []

    @patch('asv.extraction.llm_client.genai')
    def test_extract_claims_sets_location(self, mock_genai, sample_claims_data):
        """Test that location information is set for claims"""
        _set_response(mock_genai, json.dumps(sample_claims_data))

        client = LLMClient()
        result = client.extract_claims_from_chunk("Sample text", chunk_id=5)

        for claim in result:
            assert claim.location_in_text is not None
            assert claim.location_in_text.chunk_id == 5

    @patch('asv.extraction.llm_client.genai')
    def test_extract_claims_reconciles_original_with_citation(self, mock_genai):
        """A claim the LLM marks original *and* cited is kept, with is_original
        coerced to False (the citation marker wins) rather than dropped."""
        claim = {
            "claim_text": "Our result matches prior work",
            "claim_type": "qualitative",
            "citation_marker": "[1]",
            "is_original": True,
        }
        _set_response(mock_genai, json.dumps([claim]))

        client = LLMClient()
        result = client.extract_claims_from_chunk("Sample text", chunk_id=0)

        assert len(result) == 1
        assert result[0].citation_found is True
        assert result[0].is_original is False

    @patch('asv.extraction.llm_client.genai')
    def test_extract_claims_skips_malformed_claim_keeps_valid(self, mock_genai):
        """One malformed claim must not discard the whole chunk — the valid
        claims around it are still returned."""
        claims = [
            {"claim_text": "Valid claim one", "claim_type": "qualitative",
             "citation_marker": None, "is_original": True},
            # text must be a string; a list fails ClaimObject validation.
            {"claim_text": ["not", "a", "string"], "claim_type": "qualitative",
             "citation_marker": None, "is_original": False},
            {"claim_text": "Valid claim two", "claim_type": "quantitative",
             "citation_marker": "[2]", "is_original": False},
        ]
        _set_response(mock_genai, json.dumps(claims))

        client = LLMClient()
        result = client.extract_claims_from_chunk("Sample text", chunk_id=0)

        texts = [c.text for c in result]
        assert texts == ["Valid claim one", "Valid claim two"]


class TestParseReferencesWithLLM:
    """Tests for parse_references_with_llm method"""

    @patch('asv.extraction.llm_client.genai')
    def test_parse_references_basic(self, mock_genai, sample_citations_dict):
        """Test basic reference parsing"""
        _set_response(mock_genai, json.dumps(sample_citations_dict))

        client = LLMClient()
        result = client.parse_references_with_llm("References section text")

        assert isinstance(result, dict)
        assert len(result) == len(sample_citations_dict)
        assert "1" in result

    @patch('asv.extraction.llm_client.genai')
    def test_parse_references_wrapped_format(self, mock_genai, sample_citations_dict):
        """Test parsing with wrapped citations format"""
        _set_response(mock_genai, json.dumps({"citations": sample_citations_dict}))

        client = LLMClient()
        result = client.parse_references_with_llm("References section text")

        assert result == sample_citations_dict

    @patch('asv.extraction.llm_client.genai')
    def test_parse_references_tracks_tokens(self, mock_genai):
        """Test that token usage is tracked"""
        _set_response(mock_genai, json.dumps({}), prompt_tokens=234, candidate_tokens=567)

        client = LLMClient()
        client.parse_references_with_llm("References text")

        assert client.total_input_tokens == 234
        assert client.total_output_tokens == 567

    @patch('asv.extraction.llm_client.genai')
    def test_parse_references_error_handling(self, mock_genai):
        """Test error handling when parsing fails"""
        _set_error(mock_genai, Exception("API Error"))

        client = LLMClient()
        result = client.parse_references_with_llm("References text")

        assert result == {}

    @patch('asv.extraction.llm_client.genai')
    def test_parse_references_empty_response(self, mock_genai):
        """Test handling of empty response"""
        _set_response(mock_genai, None, candidate_tokens=0)

        client = LLMClient()
        result = client.parse_references_with_llm("References text")

        assert result == {}


class TestCallLLM:
    """Tests for generic call_llm method"""

    @patch('asv.extraction.llm_client.genai')
    def test_call_llm_json_format(self, mock_genai):
        """Test LLM call with JSON response format"""
        _set_response(mock_genai, json.dumps({"result": "success"}), prompt_tokens=50, candidate_tokens=30)

        client = LLMClient()
        result = client.call_llm("Test prompt", response_format="json")

        assert isinstance(result, dict)
        assert result["result"] == "success"

    @patch('asv.extraction.llm_client.genai')
    def test_call_llm_text_format(self, mock_genai):
        """Test LLM call with text response format"""
        _set_response(mock_genai, "Plain text response", prompt_tokens=50, candidate_tokens=30)

        client = LLMClient()
        result = client.call_llm("Test prompt", response_format="text")

        assert isinstance(result, str)
        assert result == "Plain text response"

    @patch('asv.extraction.llm_client.genai')
    def test_call_llm_tracks_tokens(self, mock_genai):
        """Test that token usage is tracked"""
        _set_response(mock_genai, "Response", prompt_tokens=111, candidate_tokens=222)

        client = LLMClient()
        client.call_llm("Test prompt", response_format="text")

        assert client.total_input_tokens == 111
        assert client.total_output_tokens == 222

    @patch('asv.extraction.llm_client.genai')
    def test_call_llm_error_handling_json(self, mock_genai):
        """Test error handling for JSON format"""
        _set_error(mock_genai, Exception("API Error"))

        client = LLMClient()
        result = client.call_llm("Test prompt", response_format="json")

        assert result == {}

    @patch('asv.extraction.llm_client.genai')
    def test_call_llm_error_handling_text(self, mock_genai):
        """Test error handling for text format"""
        _set_error(mock_genai, Exception("API Error"))

        client = LLMClient()
        result = client.call_llm("Test prompt", response_format="text")

        assert result == ""

    @patch('asv.extraction.llm_client.genai')
    def test_call_llm_empty_json_response(self, mock_genai):
        """Test handling of empty JSON response"""
        _set_response(mock_genai, None, prompt_tokens=50, candidate_tokens=0)

        client = LLMClient()
        result = client.call_llm("Test prompt", response_format="json")

        assert result == {}

    @patch('asv.extraction.llm_client.genai')
    def test_call_llm_empty_text_response(self, mock_genai):
        """Test handling of empty text response"""
        _set_response(mock_genai, None, prompt_tokens=50, candidate_tokens=0)

        client = LLMClient()
        result = client.call_llm("Test prompt", response_format="text")

        assert result == ""


class TestGetCostSummary:
    """Tests for get_cost_summary method"""

    @patch('asv.extraction.llm_client.genai')
    def test_cost_summary_initial_state(self, mock_genai):
        """Test cost summary with no API calls"""
        client = LLMClient()
        summary = client.get_cost_summary()

        assert summary['input_tokens'] == 0
        assert summary['output_tokens'] == 0
        assert summary['total_tokens'] == 0
        assert summary['input_cost'] == 0.0
        assert summary['output_cost'] == 0.0
        assert summary['total_cost'] == 0.0

    @patch('asv.extraction.llm_client.genai')
    def test_cost_summary_after_api_calls(self, mock_genai):
        """Test cost summary after making API calls"""
        _set_response(mock_genai, json.dumps({"claims": []}), prompt_tokens=1000, candidate_tokens=500)

        client = LLMClient()
        client.extract_claims_from_chunk("Test text", chunk_id=0)

        summary = client.get_cost_summary()

        assert summary['input_tokens'] == 1000
        assert summary['output_tokens'] == 500
        assert summary['total_tokens'] == 1500
        assert summary['input_cost'] > 0
        assert summary['output_cost'] > 0
        assert summary['total_cost'] == summary['input_cost'] + summary['output_cost']

    @patch('asv.extraction.llm_client.genai')
    def test_cost_calculation_accuracy(self, mock_genai):
        """Test that cost calculation uses correct Gemini pricing.

        get_cost_summary bills $0.10/M input tokens and $0.40/M output tokens.
        """
        _set_response(
            mock_genai, json.dumps({"claims": []}),
            prompt_tokens=1_000_000, candidate_tokens=1_000_000,
        )

        client = LLMClient()
        client.extract_claims_from_chunk("Test text", chunk_id=0)

        summary = client.get_cost_summary()

        assert abs(summary['input_cost'] - 0.10) < 0.001
        assert abs(summary['output_cost'] - 0.40) < 0.001
        assert abs(summary['total_cost'] - 0.50) < 0.001

    @patch('asv.extraction.llm_client.genai')
    def test_cost_summary_accumulates(self, mock_genai):
        """Test that costs accumulate across multiple calls"""
        _set_response(mock_genai, json.dumps({}), prompt_tokens=100, candidate_tokens=50)

        client = LLMClient()
        client.call_llm("First call", response_format="json")
        client.call_llm("Second call", response_format="json")

        summary = client.get_cost_summary()

        assert summary['input_tokens'] == 200
        assert summary['output_tokens'] == 100
        assert summary['total_tokens'] == 300
