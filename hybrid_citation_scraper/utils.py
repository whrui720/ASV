"""Utility functions for PDF extraction and text processing"""

import re
from typing import List, Dict, Optional, Tuple, Any
from pathlib import Path
import tiktoken
from langchain_community.document_loaders import PyPDFLoader

from .config import REFERENCE_KEYWORDS, CITATION_STYLES, CHUNK_SIZE, CHUNK_OVERLAP


def extract_text_from_pdf(pdf_path: str) -> str:
    """Extract text from PDF file using LangChain's PyPDFLoader"""
    loader = PyPDFLoader(pdf_path)
    pages = loader.load()
    # Combine all pages into single text
    return '\n\n'.join([page.page_content for page in pages])


def extract_title_and_abstract(full_text: str) -> Dict[str, Optional[str]]:
    """
    Extract title and abstract from PDF text.
    Returns dict with 'title' and 'abstract' keys.
    """
    lines = full_text.split('\n')
    title = None
    abstract = None
    
    # Try to extract title (usually first non-empty line or first few lines)
    for i, line in enumerate(lines[:10]):
        line = line.strip()
        if line and len(line) > 10 and not line.isupper():
            title = line
            break
    
    # Try to find abstract section
    abstract_keywords = ['abstract', 'summary', 'synopsis']
    for i, line in enumerate(lines[:50]):
        line_lower = line.lower().strip()
        if any(keyword in line_lower for keyword in abstract_keywords):
            # Found abstract header, collect following lines until next section
            abstract_lines = []
            for j in range(i+1, min(i+30, len(lines))):
                next_line = lines[j].strip()
                if not next_line:
                    continue
                # Stop at next section header (all caps or specific keywords)
                if (next_line.isupper() and len(next_line) > 5) or \
                   any(keyword in next_line.lower() for keyword in ['introduction', 'background', 'keywords', '1.']):
                    break
                abstract_lines.append(next_line)
            
            if abstract_lines:
                abstract = ' '.join(abstract_lines)
                break
    
    return {
        'title': title,
        'abstract': abstract
    }


def locate_reference_section(full_text: str) -> Optional[str]:
    """
    Deterministically locate the reference section in text.
    Returns the reference section text or None if not found.
    """
    # Try each reference keyword
    for keyword in REFERENCE_KEYWORDS:
        # Case-insensitive search for keyword at start of line
        pattern = rf'^{keyword}\s*$'
        match = re.search(pattern, full_text, re.MULTILINE | re.IGNORECASE)
        
        if match:
            start_pos = match.end()
            # Take everything after the keyword
            # In practice, might want to detect end of references section too
            ref_section = full_text[start_pos:].strip()
            return ref_section
    
    # Fallback: look for common patterns in last 30% of document
    last_third = full_text[int(len(full_text) * 0.7):]
    for keyword in REFERENCE_KEYWORDS:
        if keyword.lower() in last_third.lower():
            idx = last_third.lower().index(keyword.lower())
            return last_third[idx:]
    
    return None


def detect_citation_style(ref_section: str) -> Optional[str]:
    """
    Detect citation format from reference section patterns.
    Returns style name or None if undetected.
    """
    if not ref_section:
        return None
    
    # Check first few lines for pattern matching
    first_lines = '\n'.join(ref_section.split('\n')[:5])
    
    for style, pattern in CITATION_STYLES.items():
        if re.search(pattern, first_lines, re.MULTILINE):
            return style
    
    return None


def parse_citations_deterministic(ref_section: str, citation_style: str) -> Dict[str, str]:
    """
    Parse citations deterministically based on detected style.
    Returns dict mapping citation_id -> citation_text
    """
    citations = {}
    
    if citation_style == 'numeric':
        # Parse "1. Author et al. Title..."
        pattern = r'^(\d+)\.\s+(.+?)(?=^\d+\.|$)'
        matches = re.finditer(pattern, ref_section, re.MULTILINE | re.DOTALL)
        
        for match in matches:
            citation_id = match.group(1)
            citation_text = match.group(2).strip()
            # Clean up extra whitespace
            citation_text = re.sub(r'\s+', ' ', citation_text)
            citations[citation_id] = citation_text
    
    elif citation_style == 'apa':
        # Parse "Smith, J. (2020). Title..."
        # This is simplified - full APA parsing is complex
        lines = ref_section.split('\n')
        current_citation = []
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Check if line starts with author pattern
            if re.match(r'^\w+,\s+\w\.', line):
                # Save previous citation if exists
                if current_citation:
                    text = ' '.join(current_citation)
                    # Use first author as key
                    key = current_citation[0].split(',')[0].strip()
                    citations[key] = text
                # Start new citation
                current_citation = [line]
            else:
                # Continue previous citation
                if current_citation:
                    current_citation.append(line)
        
        # Save last citation
        if current_citation:
            text = ' '.join(current_citation)
            key = current_citation[0].split(',')[0].strip()
            citations[key] = text
    
    # Add other citation styles as needed
    
    return citations


def validate_citations(citations: Dict[str, str], min_citations: int = 1) -> bool:
    """
    Validate that parsed citations look reasonable.
    Returns True if citations seem valid.
    """
    if len(citations) < min_citations:
        return False
    
    # Check that citations aren't too short or too long
    for citation_text in citations.values():
        if len(citation_text) < 20 or len(citation_text) > 2000:
            return False
    
    return True


def count_tokens(text: str, model: str = "gpt-4o-mini") -> int:
    """Count tokens in text using tiktoken"""
    encoding = tiktoken.encoding_for_model(model)
    return len(encoding.encode(text))


def semantic_chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[Dict[str, Any]]:
    """
    Chunk text using sentence boundaries with character-level overlap.
    
    Strategy:
    - Split on sentence boundaries to never split claims mid-sentence
    - Add small character overlap (default 100 chars) as safety net for multi-sentence claims
    - Track character positions for accurate claim location mapping
    
    Args:
        text: Input text to chunk
        chunk_size: Target size in tokens (soft limit)
        overlap: Character overlap between chunks (default 100)
    
    Returns:
        List of dicts with chunk_id, text, start_pos, end_pos, token_count
    """
    # Split into sentences at natural boundaries
    sentences = re.split(r'(?<=[.!?])\s+', text)
    
    chunks = []
    current_chunk = []
    current_tokens = 0
    chunk_start_pos = 0
    
    for sentence in sentences:
        sentence_tokens = count_tokens(sentence)
        
        # Check if adding this sentence would exceed chunk size
        if current_tokens + sentence_tokens > chunk_size and current_chunk:
            # Finalize current chunk
            chunk_text = ' '.join(current_chunk)
            chunks.append({
                'chunk_id': len(chunks),
                'text': chunk_text,
                'start_pos': chunk_start_pos,
                'end_pos': chunk_start_pos + len(chunk_text),
                'token_count': current_tokens
            })
            
            # Start new chunk with character overlap from previous chunk
            if overlap > 0 and len(chunk_text) >= overlap:
                overlap_text = chunk_text[-overlap:]
                # Find sentence boundary within overlap text
                overlap_sentences = []
                temp_text = overlap_text
                for sent in reversed(current_chunk):
                    if len(' '.join([sent] + overlap_sentences)) <= overlap:
                        overlap_sentences.insert(0, sent)
                    else:
                        break
                
                current_chunk = overlap_sentences + [sentence]
                current_tokens = sum(count_tokens(s) for s in current_chunk)
                # Adjust start position accounting for overlap
                chunk_start_pos = chunk_start_pos + len(chunk_text) - len(' '.join(overlap_sentences))
            else:
                current_chunk = [sentence]
                current_tokens = sentence_tokens
                chunk_start_pos += len(chunk_text) + 1  # +1 for space
        else:
            current_chunk.append(sentence)
            current_tokens += sentence_tokens
    
    # Add final chunk
    if current_chunk:
        chunk_text = ' '.join(current_chunk)
        chunks.append({
            'chunk_id': len(chunks),
            'text': chunk_text,
            'start_pos': chunk_start_pos,
            'end_pos': chunk_start_pos + len(chunk_text),
            'token_count': current_tokens
        })
    
    return chunks


def extract_citation_markers(text: str) -> List[str]:
    """
    Extract citation markers from text.
    Returns list of citation markers found (e.g., ["[1]", "[2]", "(Smith, 2020)"])
    """
    markers = []
    
    # Numeric citations: [1], [2], etc.
    numeric = re.findall(r'\[\d+\]', text)
    markers.extend(numeric)
    
    # Author-year citations: (Smith, 2020), (Jones et al., 2019)
    author_year = re.findall(r'\([A-Z][a-z]+(?:\s+et al\.)?,\s+\d{4}\)', text)
    markers.extend(author_year)
    
    # Superscript numbers (captured as regular numbers after superscript)
    # This is tricky with plain text - may need special handling
    
    return list(set(markers))  # Remove duplicates
