# Testing Suite for Hybrid Citation Scraper

Comprehensive test suite for the `hybrid_citation_scraper` module, covering all functionality with unit tests, integration tests, and mocked external dependencies.

## Test Coverage

### Modules Tested

1. **test_utils.py** - Tests for utility functions
   - PDF text extraction
   - Title and abstract extraction
   - Reference section location
   - Citation style detection
   - Citation parsing (deterministic)
   - Citation validation
   - Token counting
   - Text chunking with semantic boundaries
   - Citation marker extraction

2. **test_llm_client.py** - Tests for LLM client
   - Claim extraction from chunks (with mocked OpenAI calls)
   - Reference parsing with LLM
   - Generic LLM calls
   - Cost tracking and calculation
   - Error handling

3. **test_claim_extractor.py** - Tests for main claim extraction pipeline
   - Citation extraction (hybrid approach)
   - Claim extraction from text
   - Citation-to-claim mapping
   - Claim sorting and grouping
   - Complete PDF processing pipeline
   - Result saving

4. **test_config.py** - Tests for configuration
   - Configuration loading
   - Environment variable handling
   - Citation style patterns
   - Configuration constants validation

## Installation

Install test dependencies:

```bash
pip install -r test_requirements.txt
```

Or install individually:

```bash
pip install pytest pytest-cov pytest-mock coverage
```

## Running Tests

### Run all tests
```bash
pytest
```

### Run with coverage report
```bash
pytest --cov=hybrid_citation_scraper --cov-report=html
```

### Run specific test file
```bash
pytest hybrid_citation_scraper/tests/test_utils.py
```

### Run specific test class
```bash
pytest hybrid_citation_scraper/tests/test_utils.py::TestExtractTextFromPDF
```

### Run specific test
```bash
pytest hybrid_citation_scraper/tests/test_utils.py::TestExtractTextFromPDF::test_extract_text_from_pdf_success
```

### Run with verbose output
```bash
pytest -v
```

### Run tests by marker
```bash
pytest -m unit          # Run only unit tests
pytest -m integration   # Run only integration tests
pytest -m "not slow"    # Skip slow tests
```

## Test Structure

```
hybrid_citation_scraper/tests/
├── __init__.py
├── conftest.py              # Shared fixtures and test configuration
├── test_utils.py            # Tests for utils module
├── test_llm_client.py       # Tests for LLM client
├── test_claim_extractor.py  # Tests for claim extractor
├── test_config.py           # Tests for configuration
└── test_requirements.txt    # Test dependencies
```

## Fixtures

Common fixtures are defined in `conftest.py`:

- `sample_pdf_text` - Sample PDF content
- `sample_references_section` - Sample reference section
- `sample_citations_dict` - Parsed citations
- `sample_claims_data` - Sample claim data
- `mock_openai_client` - Mocked OpenAI client
- `mock_llm_response` - Mocked LLM response builder
- `sample_claim_objects` - Sample ClaimObject instances
- `temp_pdf_file` - Temporary PDF file path
- `mock_pdf_loader` - Mocked PDF loader

## Mocking Strategy

### OpenAI API Calls
All OpenAI API calls are mocked using `unittest.mock.patch` to:
- Avoid actual API calls during tests
- Control response data for deterministic testing
- Test error handling without making failed API calls
- Verify proper token tracking

### PDF Loading
PDF loading is mocked to avoid needing actual PDF files:
- Mock PyPDFLoader returns test data
- Allows testing PDF processing without file dependencies

## Coverage Goals

Target: **>90% code coverage** for all modules

Current coverage:
- `utils.py`: All functions tested
- `llm_client.py`: All methods tested with mocking
- `claim_extractor.py`: Complete pipeline tested
- `config.py`: Configuration validation tested

## Continuous Integration

Tests can be integrated into CI/CD pipelines:

```yaml
# Example GitHub Actions workflow
- name: Run tests
  run: |
    pip install -r hybrid_citation_scraper/tests/test_requirements.txt
    pytest --cov=hybrid_citation_scraper --cov-report=xml
```

## Writing New Tests

### Example Test Structure

```python
import pytest
from hybrid_citation_scraper.utils import your_function

class TestYourFunction:
    """Tests for your_function"""
    
    def test_basic_functionality(self):
        """Test basic case"""
        result = your_function("input")
        assert result == "expected"
    
    def test_edge_case(self):
        """Test edge case"""
        result = your_function("")
        assert result is None
    
    def test_error_handling(self):
        """Test error handling"""
        with pytest.raises(ValueError):
            your_function(None)
```

### Using Fixtures

```python
def test_with_fixture(sample_pdf_text):
    """Test using shared fixture"""
    assert len(sample_pdf_text) > 0
```

### Mocking External Calls

```python
from unittest.mock import patch

@patch('module.external_call')
def test_with_mock(mock_external):
    """Test with mocked external dependency"""
    mock_external.return_value = "mocked result"
    # Your test code here
```

## Troubleshooting

### Import Errors
Ensure the package is installed in development mode:
```bash
pip install -e .
```

### Missing Dependencies
Install all test dependencies:
```bash
pip install -r hybrid_citation_scraper/tests/test_requirements.txt
```

### Coverage Not Working
Install coverage package:
```bash
pip install pytest-cov coverage
```

## Best Practices

1. **Isolation**: Each test should be independent
2. **Descriptive Names**: Use clear test function names
3. **One Assert Per Test**: Focus each test on one behavior
4. **Use Fixtures**: Reuse test data via fixtures
5. **Mock External Calls**: Don't rely on external services
6. **Test Edge Cases**: Cover boundary conditions
7. **Test Error Paths**: Verify error handling

## Future Improvements

- [ ] Add integration tests with real PDF files (optional)
- [ ] Add performance benchmarking tests
- [ ] Add tests for concurrent processing
- [ ] Add property-based testing with Hypothesis
- [ ] Add mutation testing with mutmut
