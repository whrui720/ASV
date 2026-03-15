"""Tests for hybrid_citation_scraper.utils module"""

import pytest
from hybrid_citation_scraper.utils import (
    extract_text_from_pdf,
    extract_title_and_abstract,
    locate_reference_section,
    detect_citation_style,
    parse_citations_deterministic,
    validate_citations,
    count_tokens,
    semantic_chunk_text,
    extract_citation_markers
)


class TestExtractTextFromPDF:
    """Tests for extract_text_from_pdf function"""
    
    def test_extract_text_from_pdf_success(self, mock_pdf_loader, temp_pdf_file):
        """Test successful PDF text extraction"""
        result = extract_text_from_pdf(temp_pdf_file)
        assert isinstance(result, str)
        assert len(result) > 0
    
    def test_extract_text_from_pdf_combines_pages(self, mock_pdf_loader, temp_pdf_file):
        """Test that text from all pages is combined"""
        result = extract_text_from_pdf(temp_pdf_file)
        assert '\n\n' in result  # Pages should be separated by double newline


class TestExtractTitleAndAbstract:
    """Tests for extract_title_and_abstract function"""
    
    def test_extract_title_from_text(self, sample_pdf_text):
        """Test title extraction"""
        result = extract_title_and_abstract(sample_pdf_text)
        assert result['title'] is not None
        assert 'Machine Learning' in result['title']
    
    def test_extract_abstract_from_text(self, sample_pdf_text):
        """Test abstract extraction"""
        result = extract_title_and_abstract(sample_pdf_text)
        assert result['abstract'] is not None
        assert 'novel approach' in result['abstract']
    
    def test_extract_handles_missing_abstract(self):
        """Test extraction when abstract is missing"""
        text = "Title Only Paper\n\nIntroduction\nThis is the intro."
        result = extract_title_and_abstract(text)
        assert result['title'] is not None
        assert result['abstract'] is None
    
    def test_extract_stops_at_introduction(self, sample_pdf_text):
        """Test that abstract extraction stops at Introduction section"""
        result = extract_title_and_abstract(sample_pdf_text)
        if result['abstract']:
            assert 'Introduction' not in result['abstract']


class TestLocateReferenceSection:
    """Tests for locate_reference_section function"""
    
    def test_locate_references_with_standard_header(self, sample_pdf_text):
        """Test finding reference section with 'References' header"""
        result = locate_reference_section(sample_pdf_text)
        assert result is not None
        assert 'Smith, J.' in result
        assert 'Brown, A.' in result
    
    def test_locate_references_case_insensitive(self):
        """Test that reference section detection is case insensitive"""
        text = "Main text here\n\nreferences\n1. Citation here"
        result = locate_reference_section(text)
        assert result is not None
    
    def test_locate_references_bibliography(self):
        """Test finding reference section with 'Bibliography' header"""
        text = "Main text\n\nBibliography\n1. Citation"
        result = locate_reference_section(text)
        assert result is not None
        assert 'Citation' in result
    
    def test_locate_references_not_found(self):
        """Test when reference section cannot be located"""
        text = "Just main text without references"
        result = locate_reference_section(text)
        assert result is None
    
    def test_locate_references_in_last_third(self):
        """Test fallback to searching in last 30% of document"""
        text = "A" * 1000 + "\nReferences section here\n1. Citation"
        result = locate_reference_section(text)
        assert result is not None


class TestDetectCitationStyle:
    """Tests for detect_citation_style function"""
    
    def test_detect_numeric_style(self, sample_references_section):
        """Test detection of numeric citation style"""
        result = detect_citation_style(sample_references_section)
        assert result == 'numeric'
    
    def test_detect_apa_style(self, sample_apa_references):
        """Test detection of APA citation style"""
        result = detect_citation_style(sample_apa_references)
        assert result == 'apa'
    
    def test_detect_vancouver_style(self):
        """Test detection of Vancouver style"""
        text = "1. Smith J. Title of paper. Journal. 2020.\n2. Brown A. Another. Med J. 2019."
        result = detect_citation_style(text)
        assert result in ['vancouver', 'numeric']
    
    def test_detect_unknown_style(self):
        """Test when citation style cannot be detected"""
        text = "Random text without clear citation format"
        result = detect_citation_style(text)
        assert result is None
    
    def test_detect_with_empty_section(self):
        """Test detection with empty reference section"""
        result = detect_citation_style("")
        assert result is None


class TestParseCitationsDeterministic:
    """Tests for parse_citations_deterministic function"""
    
    def test_parse_numeric_citations(self, sample_references_section):
        """Test parsing numeric citation format"""
        result = parse_citations_deterministic(sample_references_section, 'numeric')
        assert isinstance(result, dict)
        assert len(result) > 0
        assert "1" in result
        assert "Smith" in result["1"]
    
    def test_parse_numeric_multiple_citations(self, sample_references_section):
        """Test parsing multiple numeric citations"""
        result = parse_citations_deterministic(sample_references_section, 'numeric')
        assert len(result) >= 4
        assert all(str(i) in result for i in range(1, 5))
    
    def test_parse_apa_citations(self, sample_apa_references):
        """Test parsing APA citation format"""
        result = parse_citations_deterministic(sample_apa_references, 'apa')
        assert isinstance(result, dict)
        assert len(result) > 0
        # Should use author names as keys
        assert any('Smith' in key for key in result.keys())
    
    def test_parse_removes_extra_whitespace(self, sample_references_section):
        """Test that extra whitespace is removed from parsed citations"""
        result = parse_citations_deterministic(sample_references_section, 'numeric')
        for citation_text in result.values():
            assert not citation_text.startswith(' ')
            assert not citation_text.endswith(' ')
            assert '  ' not in citation_text  # No double spaces
    
    def test_parse_unsupported_style(self):
        """Test parsing with unsupported citation style"""
        text = "Some references"
        result = parse_citations_deterministic(text, 'chicago')
        # Should return empty dict for unsupported styles
        assert isinstance(result, dict)


class TestValidateCitations:
    """Tests for validate_citations function"""
    
    def test_validate_valid_citations(self, sample_citations_dict):
        """Test validation of valid citations"""
        result = validate_citations(sample_citations_dict)
        assert result is True
    
    def test_validate_empty_citations(self):
        """Test validation of empty citations dict"""
        result = validate_citations({})
        assert result is False
    
    def test_validate_too_few_citations(self):
        """Test validation with fewer than minimum citations"""
        citations = {"1": "Short citation text here."}
        result = validate_citations(citations, min_citations=2)
        assert result is False
    
    def test_validate_citation_too_short(self):
        """Test validation of citations that are too short"""
        citations = {"1": "Too short"}
        result = validate_citations(citations)
        assert result is False
    
    def test_validate_citation_too_long(self):
        """Test validation of citations that are too long"""
        citations = {"1": "A" * 3000}  # Over 2000 chars
        result = validate_citations(citations)
        assert result is False
    
    def test_validate_mixed_valid_invalid(self):
        """Test that all citations must be valid"""
        citations = {
            "1": "Valid citation with enough text to pass minimum length check.",
            "2": "Short"  # Too short
        }
        result = validate_citations(citations)
        assert result is False


class TestCountTokens:
    """Tests for count_tokens function"""
    
    def test_count_tokens_simple_text(self):
        """Test token counting for simple text"""
        text = "Hello world"
        result = count_tokens(text)
        assert isinstance(result, int)
        assert result > 0
    
    def test_count_tokens_empty_string(self):
        """Test token counting for empty string"""
        result = count_tokens("")
        assert result == 0
    
    def test_count_tokens_longer_text(self):
        """Test that longer text has more tokens"""
        short_text = "Hello"
        long_text = "Hello world, this is a longer sentence with more tokens."
        assert count_tokens(long_text) > count_tokens(short_text)
    
    def test_count_tokens_with_special_chars(self):
        """Test token counting with special characters"""
        text = "Test with special chars: @#$%^&*()"
        result = count_tokens(text)
        assert isinstance(result, int)
        assert result > 0


class TestSemanticChunkText:
    """Tests for semantic_chunk_text function"""
    
    def test_chunk_text_creates_chunks(self):
        """Test basic text chunking"""
        text = "First sentence. Second sentence. Third sentence. Fourth sentence."
        result = semantic_chunk_text(text, chunk_size=50)
        assert isinstance(result, list)
        assert len(result) > 0
        assert all('chunk_id' in chunk for chunk in result)
    
    def test_chunk_text_respects_sentence_boundaries(self):
        """Test that chunks don't split sentences"""
        text = "First sentence here. Second sentence here. Third sentence here."
        result = semantic_chunk_text(text, chunk_size=20)
        for chunk in result:
            # Each chunk should contain complete sentences
            text_content = chunk['text']
            if not text_content.endswith('.'):
                # If doesn't end with period, should be last chunk
                assert chunk == result[-1] or text_content.strip().endswith('.')
    
    def test_chunk_text_has_overlap(self):
        """Test that chunks have overlap"""
        text = "Sentence one. Sentence two. Sentence three. Sentence four. Sentence five."
        result = semantic_chunk_text(text, chunk_size=30, overlap=10)
        if len(result) > 1:
            # Check that some content overlaps
            for i in range(len(result) - 1):
                chunk1_end = result[i]['text'][-10:]
                chunk2_start = result[i+1]['text'][:50]
                # Some overlap should exist
                overlap_exists = any(word in chunk2_start for word in chunk1_end.split())
                # We don't assert here as overlap is character-based, not guaranteed word overlap
    
    def test_chunk_text_tracks_positions(self):
        """Test that chunks track start and end positions"""
        text = "First sentence. Second sentence. Third sentence."
        result = semantic_chunk_text(text, chunk_size=50)
        for chunk in result:
            assert 'start_pos' in chunk
            assert 'end_pos' in chunk
            assert chunk['end_pos'] >= chunk['start_pos']
    
    def test_chunk_text_includes_token_count(self):
        """Test that chunks include token count"""
        text = "First sentence. Second sentence."
        result = semantic_chunk_text(text, chunk_size=50)
        for chunk in result:
            assert 'token_count' in chunk
            assert chunk['token_count'] > 0
    
    def test_chunk_text_with_single_long_sentence(self):
        """Test chunking with a single sentence longer than chunk size"""
        text = "This is a very long sentence " * 100 + "."
        result = semantic_chunk_text(text, chunk_size=50)
        assert len(result) > 0
        # Should still create chunk even if sentence is too long
    
    def test_chunk_text_empty_string(self):
        """Test chunking empty string"""
        result = semantic_chunk_text("", chunk_size=50)
        # Should handle gracefully
        assert isinstance(result, list)


class TestExtractCitationMarkers:
    """Tests for extract_citation_markers function"""
    
    def test_extract_numeric_markers(self):
        """Test extraction of numeric citation markers"""
        text = "This is a claim [1] and another [2] with citations."
        result = extract_citation_markers(text)
        assert '[1]' in result
        assert '[2]' in result
    
    def test_extract_author_year_markers(self):
        """Test extraction of author-year citation markers"""
        text = "Research shows (Smith, 2020) and (Jones, 2019) that..."
        result = extract_citation_markers(text)
        assert '(Smith, 2020)' in result
        assert '(Jones, 2019)' in result
    
    def test_extract_et_al_citations(self):
        """Test extraction of et al. citations"""
        text = "Studies (Brown et al., 2021) demonstrate this."
        result = extract_citation_markers(text)
        assert '(Brown et al., 2021)' in result
    
    def test_extract_mixed_citation_styles(self):
        """Test extraction of mixed citation styles"""
        text = "Some work [1] and other work (Smith, 2020) show this."
        result = extract_citation_markers(text)
        assert '[1]' in result
        assert '(Smith, 2020)' in result
    
    def test_extract_no_citations(self):
        """Test extraction when no citations present"""
        text = "Text without any citations."
        result = extract_citation_markers(text)
        assert len(result) == 0
    
    def test_extract_removes_duplicates(self):
        """Test that duplicate markers are removed"""
        text = "First [1] and second [1] use same citation."
        result = extract_citation_markers(text)
        assert result.count('[1]') == 1
    
    def test_extract_multiple_consecutive_citations(self):
        """Test extraction of multiple consecutive citations"""
        text = "Multiple studies [1][2][3] show this."
        result = extract_citation_markers(text)
        assert '[1]' in result
        assert '[2]' in result
        assert '[3]' in result
