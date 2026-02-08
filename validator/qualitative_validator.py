"""Qualitative Validator - RAG-based validation using TF-IDF and LLM verification"""

import logging
from typing import Dict, Any, List
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np
from hybrid_citation_scraper.llm_client import LLMClient
from models import ClaimObject, ValidationResult
from .config import RAG_TOP_K, RAG_SIMILARITY_THRESHOLD

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class QualitativeValidator:
    """Validate qualitative claims using TF-IDF RAG and LLM verification"""
    
    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client
        self.vectorizer = TfidfVectorizer(
            max_features=1000,
            stop_words='english',
            ngram_range=(1, 2)
        )
    
    def validate_claim(self, claim: ClaimObject, source_text: str) -> ValidationResult:
        """
        Validate a qualitative claim against source text using RAG.
        1. Split source into chunks
        2. Use TF-IDF to find most relevant chunks
        3. Ask LLM to verify claim against retrieved chunks
        """
        logger.info(f"Validating qualitative claim: {claim.claim_id}")
        
        try:
            # Step 1: Split source into chunks
            chunks = self._split_into_chunks(source_text)
            
            if not chunks:
                return ValidationResult(
                    claim_id=claim.claim_id,
                    claim_type=claim.claim_type,
                    originally_uncited=claim.originally_uncited,
                    validated=False,
                    validation_method="rag_search",
                    confidence=0.0,
                    passed=False,
                    explanation="Source text is empty or could not be chunked",
                    sources_used=[],
                    errors="No content to validate against"
                )
            
            # Step 2: Retrieve most relevant chunks using TF-IDF
            relevant_chunks = self._retrieve_relevant_chunks(claim.text, chunks)
            
            if not relevant_chunks:
                return ValidationResult(
                    claim_id=claim.claim_id,
                    claim_type=claim.claim_type,
                    originally_uncited=claim.originally_uncited,
                    validated=False,
                    validation_method="rag_search",
                    confidence=0.0,
                    passed=False,
                    explanation="No relevant chunks found in source",
                    sources_used=[],
                    errors="Low similarity scores"
                )
            
            logger.info(f"  Retrieved {len(relevant_chunks)} relevant chunks")
            
            # Step 3: Use LLM to verify claim against retrieved chunks
            verification = self._verify_with_llm(claim.text, relevant_chunks)
            
            return ValidationResult(
                claim_id=claim.claim_id,
                claim_type=claim.claim_type,
                originally_uncited=claim.originally_uncited,
                validated=True,
                validation_method="rag_search",
                confidence=verification['confidence'],
                passed=verification['passed'],
                explanation=verification['explanation'],
                sources_used=verification['supporting_quotes'],
                errors=None
            )
        
        except Exception as e:
            logger.error(f"Validation error: {str(e)}")
            return ValidationResult(
                claim_id=claim.claim_id,
                claim_type=claim.claim_type,
                originally_uncited=claim.originally_uncited,
                validated=False,
                validation_method="rag_search",
                confidence=0.0,
                passed=False,
                explanation="Validation error occurred",
                sources_used=[],
                errors=str(e)
            )
    
    def _split_into_chunks(self, text: str, chunk_size: int = 500) -> List[str]:
        """Split text into overlapping chunks for RAG"""
        if not text or len(text.strip()) == 0:
            return []
        
        # Simple sentence-based chunking
        sentences = text.replace('\n', ' ').split('. ')
        chunks = []
        current_chunk = []
        current_length = 0
        
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            
            sentence_length = len(sentence)
            
            if current_length + sentence_length > chunk_size and current_chunk:
                # Save current chunk
                chunks.append('. '.join(current_chunk) + '.')
                # Keep last sentence for overlap
                current_chunk = [current_chunk[-1]] if current_chunk else []
                current_length = len(current_chunk[0]) if current_chunk else 0
            
            current_chunk.append(sentence)
            current_length += sentence_length
        
        # Add final chunk
        if current_chunk:
            chunks.append('. '.join(current_chunk) + '.')
        
        return chunks
    
    def _retrieve_relevant_chunks(self, query: str, chunks: List[str]) -> List[Dict[str, Any]]:
        """Use TF-IDF to retrieve most relevant chunks"""
        if len(chunks) == 0:
            return []
        
        try:
            # Combine query with chunks for vectorization
            all_texts = [query] + chunks
            
            # Fit vectorizer and transform
            tfidf_matrix = self.vectorizer.fit_transform(all_texts)
            
            # Calculate similarity between query and all chunks
            query_vector = tfidf_matrix[0:1]  # type: ignore
            chunk_vectors = tfidf_matrix[1:]  # type: ignore
            similarities = cosine_similarity(query_vector, chunk_vectors)[0]
            
            # Get top-k chunks above threshold
            relevant_indices = []
            for idx, score in enumerate(similarities):
                if score >= RAG_SIMILARITY_THRESHOLD:
                    relevant_indices.append((idx, score))
            
            # Sort by score and take top-k
            relevant_indices.sort(key=lambda x: x[1], reverse=True)
            relevant_indices = relevant_indices[:RAG_TOP_K]
            
            # Return chunks with scores
            results = []
            for idx, score in relevant_indices:
                results.append({
                    'text': chunks[idx],
                    'score': float(score)
                })
            
            return results
        
        except Exception as e:
            logger.error(f"RAG retrieval error: {str(e)}")
            # Fallback: return first few chunks
            return [{'text': chunk, 'score': 0.5} for chunk in chunks[:RAG_TOP_K]]
    
    def _verify_with_llm(self, claim: str, relevant_chunks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Ask LLM to verify claim against retrieved chunks"""
        prompt = self._build_verification_prompt(claim, relevant_chunks)
        
        try:
            response = self.llm_client.call_llm(prompt, response_format="json")
            
            passed = response.get('passed', False)
            confidence = float(response.get('confidence', 0.5))
            explanation = response.get('explanation', 'No explanation provided')
            supporting_quotes = response.get('supporting_quotes', [])
            
            return {
                'passed': passed,
                'confidence': confidence,
                'explanation': explanation,
                'supporting_quotes': supporting_quotes
            }
        
        except Exception as e:
            logger.error(f"LLM verification error: {str(e)}")
            return {
                'passed': False,
                'confidence': 0.0,
                'explanation': f'LLM verification failed: {str(e)}',
                'supporting_quotes': []
            }
    
    def _build_verification_prompt(self, claim: str, chunks: List[Dict[str, Any]]) -> str:
        """Build prompt for LLM verification"""
        # Format retrieved chunks
        chunks_text = "\n\n".join([
            f"[Chunk {i+1}, similarity={chunk['score']:.2f}]:\n{chunk['text']}"
            for i, chunk in enumerate(chunks)
        ])
        
        return f"""You are a fact-checking assistant. Verify if a claim is supported by the provided text excerpts.

Claim to verify: "{claim}"

Retrieved relevant excerpts from source:
{chunks_text}

Task: Determine if the claim is supported by the excerpts above.

Return your response in JSON format:
{{
    "passed": true/false,
    "confidence": 0.0-1.0,
    "explanation": "Brief explanation of your assessment",
    "supporting_quotes": ["relevant quote 1", "relevant quote 2"]
}}

Guidelines:
- passed=true ONLY if the excerpts clearly support or confirm the claim
- passed=false if the excerpts contradict the claim or provide insufficient evidence
- confidence should reflect how strongly the evidence supports your decision
- supporting_quotes should contain the exact phrases/sentences that support (or contradict) the claim
- Be strict: partial matches or tangential evidence should result in passed=false
"""
