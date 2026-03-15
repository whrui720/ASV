"""Pytest configuration and shared fixtures"""

import pytest
from pathlib import Path
from typing import Dict, List
from unittest.mock import Mock, MagicMock
import json


@pytest.fixture
def sample_pdf_text():
    """Sample PDF text for testing"""
    return """
    Machine Learning for Climate Prediction
    
    Abstract
    This paper presents a novel approach to climate prediction using machine learning.
    We achieve 95% accuracy in temperature forecasting.
    
    Introduction
    Climate change is a critical issue [1]. Recent studies show temperatures rising [2].
    Our model improves on previous work by 15% [3].
    
    Methods
    We used a neural network with 10 layers. The dataset contains 100,000 samples.
    Training took 24 hours on GPU clusters.
    
    Results
    Our model achieved 95% accuracy on test data [4]. This outperforms baselines by 20%.
    The F1 score was 0.92, indicating strong performance.
    
    References
    1. Smith, J., & Jones, M. (2020). Climate Change Impacts. Nature, 123(4), 567-589.
    2. Brown, A. et al. (2019). Temperature Trends. Science, 456, 123-145.
    3. Davis, R. (2021). ML for Weather. ICML Proceedings, 789-801.
    4. Wilson, K. (2022). Forecasting Methods. Journal of AI, 15(2), 234-256.
    """


@pytest.fixture
def sample_references_section():
    """Sample reference section for testing"""
    return """
    References
    1. Smith, J., & Jones, M. (2020). Climate Change Impacts. Nature, 123(4), 567-589.
    2. Brown, A. et al. (2019). Temperature Trends. Science, 456, 123-145.
    3. Davis, R. (2021). ML for Weather. ICML Proceedings, 789-801.
    4. Wilson, K. (2022). Forecasting Methods. Journal of AI, 15(2), 234-256.
    """


@pytest.fixture
def sample_apa_references():
    """Sample APA-style references"""
    return """
    References
    Smith, J. (2020). Climate change impacts on ecosystems. Nature Climate Change.
    Brown, A. (2019). Temperature trends in the 21st century. Science Advances.
    Davis, R. (2021). Machine learning for weather prediction. ICML Proceedings.
    """


@pytest.fixture
def sample_citations_dict():
    """Sample parsed citations dictionary"""
    return {
        "1": "Smith, J., & Jones, M. (2020). Climate Change Impacts. Nature, 123(4), 567-589.",
        "2": "Brown, A. et al. (2019). Temperature Trends. Science, 456, 123-145.",
        "3": "Davis, R. (2021). ML for Weather. ICML Proceedings, 789-801.",
        "4": "Wilson, K. (2022). Forecasting Methods. Journal of AI, 15(2), 234-256."
    }


@pytest.fixture
def sample_claims_data():
    """Sample claims data from LLM response"""
    return [
        {
            "claim_text": "We achieve 95% accuracy in temperature forecasting",
            "claim_type": "quantitative",
            "citation_marker": None,
            "is_original": True
        },
        {
            "claim_text": "Climate change is a critical issue",
            "claim_type": "qualitative",
            "citation_marker": "[1]",
            "is_original": False
        },
        {
            "claim_text": "Recent studies show temperatures rising",
            "claim_type": "qualitative",
            "citation_marker": "[2]",
            "is_original": False
        },
        {
            "claim_text": "Our model improves on previous work by 15%",
            "claim_type": "quantitative",
            "citation_marker": "[3]",
            "is_original": True
        }
    ]


@pytest.fixture
def mock_openai_client():
    """Mock OpenAI client for testing"""
    mock = Mock()
    mock.chat = Mock()
    mock.chat.completions = Mock()
    return mock


@pytest.fixture
def mock_llm_response():
    """Mock LLM response object"""
    def create_response(content: str, input_tokens: int = 100, output_tokens: int = 50):
        response = Mock()
        response.choices = [Mock()]
        response.choices[0].message = Mock()
        response.choices[0].message.content = content
        response.usage = Mock()
        response.usage.prompt_tokens = input_tokens
        response.usage.completion_tokens = output_tokens
        return response
    return create_response


@pytest.fixture
def sample_chunk():
    """Sample text chunk for testing"""
    return {
        'chunk_id': 0,
        'text': 'This is a sample chunk. It contains multiple sentences. Some have citations [1].',
        'start_pos': 0,
        'end_pos': 82,
        'token_count': 20
    }


@pytest.fixture
def temp_pdf_file(tmp_path):
    """Create a temporary PDF file path"""
    pdf_path = tmp_path / "test_paper.pdf"
    return str(pdf_path)


@pytest.fixture
def temp_output_dir(tmp_path):
    """Create a temporary output directory"""
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    return str(output_dir)


@pytest.fixture
def mock_pdf_loader(monkeypatch, sample_pdf_text):
    """Mock PyPDFLoader to avoid needing actual PDF files"""
    class MockPage:
        def __init__(self, content):
            self.page_content = content
    
    class MockPDFLoader:
        def __init__(self, pdf_path):
            self.pdf_path = pdf_path
        
        def load(self):
            # Split sample text into pages
            pages = sample_pdf_text.split('\n\n')
            return [MockPage(page) for page in pages if page.strip()]
    
    def mock_loader_import(*args, **kwargs):
        return MockPDFLoader
    
    # Mock the import
    import hybrid_citation_scraper.utils as utils_module
    monkeypatch.setattr(utils_module, "PyPDFLoader", MockPDFLoader)
    
    return MockPDFLoader


@pytest.fixture
def sample_claim_object():
    """Sample ClaimObject for testing"""
    from models import ClaimObject, LocationInText
    
    return ClaimObject(
        claim_id="claim_0_0",
        text="Machine learning improves accuracy by 95%",
        claim_type="quantitative",
        citation_found=True,
        citation_id="1",
        citation_text="[1]",
        is_original=False,
        location_in_text=LocationInText(start=100, end=145, chunk_id=0)
    )


@pytest.fixture
def sample_claim_objects():
    """List of sample ClaimObject instances"""
    from models import ClaimObject, LocationInText
    
    return [
        ClaimObject(
            claim_id="claim_0_0",
            text="We achieve 95% accuracy",
            claim_type="quantitative",
            citation_found=False,
            is_original=True,
            location_in_text=LocationInText(start=0, end=23, chunk_id=0)
        ),
        ClaimObject(
            claim_id="claim_0_1",
            text="Climate change is critical",
            claim_type="qualitative",
            citation_found=True,
            citation_id="1",
            citation_text="[1]",
            is_original=False,
            location_in_text=LocationInText(start=50, end=76, chunk_id=0)
        ),
        ClaimObject(
            claim_id="claim_1_0",
            text="Temperature increased by 2 degrees",
            claim_type="quantitative",
            citation_found=True,
            citation_id="2",
            citation_text="[2]",
            is_original=False,
            location_in_text=LocationInText(start=100, end=134, chunk_id=1)
        )
    ]
