"""Tests for hybrid_citation_scraper.config module"""

import pytest
from pathlib import Path


class TestConfigLoading:
    """Tests for configuration loading"""
    
    def test_config_imports_successfully(self):
        """Test that config module can be imported"""
        from hybrid_citation_scraper import config
        assert config is not None
    
    def test_config_has_required_variables(self):
        """Test that all required configuration variables are defined"""
        from hybrid_citation_scraper import config
        
        assert hasattr(config, 'CITATION_STYLES')
        assert hasattr(config, 'REFERENCE_KEYWORDS')
        assert hasattr(config, 'CHUNK_SIZE')
        assert hasattr(config, 'CHUNK_OVERLAP')
    
    def test_citation_styles_configuration(self):
        """Test citation styles are properly configured"""
        from hybrid_citation_scraper import config
        
        assert isinstance(config.CITATION_STYLES, dict)
        assert 'numeric' in config.CITATION_STYLES
        assert 'apa' in config.CITATION_STYLES
        assert all(isinstance(pattern, str) for pattern in config.CITATION_STYLES.values())
    
    def test_reference_keywords_configuration(self):
        """Test reference keywords are properly configured"""
        from hybrid_citation_scraper import config
        
        assert isinstance(config.REFERENCE_KEYWORDS, list)
        assert len(config.REFERENCE_KEYWORDS) > 0
        assert 'References' in config.REFERENCE_KEYWORDS
        assert 'REFERENCES' in config.REFERENCE_KEYWORDS
    
    def test_chunking_settings(self):
        """Test chunking settings are properly configured"""
        from hybrid_citation_scraper import config
        
        assert isinstance(config.CHUNK_SIZE, int)
        assert config.CHUNK_SIZE > 0
        assert isinstance(config.CHUNK_OVERLAP, int)
        assert config.CHUNK_OVERLAP >= 0
        assert config.CHUNK_OVERLAP < config.CHUNK_SIZE
    



class TestCitationStylePatterns:
    """Tests for citation style regex patterns"""
    
    def test_numeric_pattern_matches(self):
        """Test numeric citation pattern"""
        import re
        from hybrid_citation_scraper.config import CITATION_STYLES
        
        pattern = CITATION_STYLES['numeric']
        assert re.match(pattern, "1. Smith et al.")
        assert re.match(pattern, "42. Jones")
    
    def test_apa_pattern_matches(self):
        """Test APA citation pattern"""
        import re
        from hybrid_citation_scraper.config import CITATION_STYLES
        
        pattern = CITATION_STYLES['apa']
        assert re.match(pattern, "Smith, J. (2020)")
        assert re.match(pattern, "Brown, A. (2019)")
    
    def test_vancouver_pattern_matches(self):
        """Test Vancouver citation pattern"""
        import re
        from hybrid_citation_scraper.config import CITATION_STYLES
        
        pattern = CITATION_STYLES['vancouver']
        assert re.match(pattern, "1. Smith J.")
        assert re.match(pattern, "10. Brown A.")


class TestConfigConstants:
    """Tests for configuration constants"""
    
    def test_all_citation_styles_present(self):
        """Test that all expected citation styles are configured"""
        from hybrid_citation_scraper.config import CITATION_STYLES
        
        expected_styles = ['numeric', 'apa', 'mla', 'chicago', 'vancouver']
        for style in expected_styles:
            assert style in CITATION_STYLES, f"Missing citation style: {style}"
    
    def test_reference_keywords_comprehensive(self):
        """Test that reference keywords cover common variations"""
        from hybrid_citation_scraper.config import REFERENCE_KEYWORDS
        
        # Should have both cases
        assert any('reference' in kw.lower() for kw in REFERENCE_KEYWORDS)
        assert any('bibliography' in kw.lower() for kw in REFERENCE_KEYWORDS)
    
    def test_chunk_size_reasonable(self):
        """Test that chunk size is reasonable for LLM processing"""
        from hybrid_citation_scraper.config import CHUNK_SIZE
        
        # Should be between 100 and 2000 tokens (reasonable range)
        assert 100 <= CHUNK_SIZE <= 2000
    
    def test_chunk_overlap_reasonable(self):
        """Test that chunk overlap is reasonable"""
        from hybrid_citation_scraper.config import CHUNK_OVERLAP, CHUNK_SIZE
        
        # Overlap should be less than 25% of chunk size
        assert CHUNK_OVERLAP < CHUNK_SIZE * 0.25
