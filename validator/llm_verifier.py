"""LLM Verifier - LLM plausibility and source-grounded verification tools"""

import logging
from typing import Dict, Any, List
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from hybrid_citation_scraper.llm_client import LLMClient
from .config import RAG_TOP_K, RAG_SIMILARITY_THRESHOLD

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class LLMVerifier:
    """Validation tool for plausibility checks and source-grounded claim verification"""
    
    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client
        self.vectorizer = TfidfVectorizer(
            max_features=1000,
            stop_words='english',
            ngram_range=(1, 2)
        )
    
    def verify_claim(self, claim_text: str) -> Dict[str, Any]:
        """
        Use LLM to verify if a claim is plausible.
        Returns dict with 'plausible', 'confidence', and 'reasoning'.
        """
        prompt = self._build_verification_prompt(claim_text)
        
        try:
            response = self.llm_client.call_llm(prompt, response_format="json")
            
            # Parse response
            plausible = response.get('plausible', False)
            confidence = float(response.get('confidence', 0.5))
            reasoning = response.get('reasoning', 'No reasoning provided')
            
            return {
                'plausible': plausible,
                'confidence': confidence,
                'reasoning': reasoning
            }
        
        except Exception as e:
            logger.error(f"LLM verification failed: {str(e)}")
            return {
                'plausible': False,
                'confidence': 0.0,
                'reasoning': f'Verification error: {str(e)}'
            }
    
    def _build_verification_prompt(self, claim_text: str) -> str:
        """Build prompt for LLM verification"""
        return f"""You are a fact-checking assistant. Evaluate the plausibility of the following claim using your general knowledge.

Claim: "{claim_text}"

Determine if this claim is plausible based on:
1. Scientific accuracy
2. Logical consistency
3. Common sense reasoning
4. Known facts and relationships

Return your response in JSON format:
{{
    "plausible": true/false,
    "confidence": 0.0-1.0 (how confident you are),
    "reasoning": "Brief explanation of your assessment"
}}

Guidelines:
- plausible=true if the claim seems reasonable and consistent with known facts
- plausible=false if the claim contradicts known facts or is highly implausible
- confidence should reflect your certainty (higher for well-known facts, lower for uncertain areas)
- reasoning should briefly explain your decision

Do NOT simply mark all claims as plausible. Be critical and evidence-based.
"""

    def verify_claim_against_source(self, claim_text: str, source_text: str) -> Dict[str, Any]:
        """
        Verify a claim against a source text using RAG + LLM.
        Returns dict with 'passed', 'confidence', 'explanation', and 'supporting_quotes'.
        """
        chunks = self._split_into_chunks(source_text)
        if not chunks:
            return {
                'passed': False,
                'confidence': 0.0,
                'explanation': 'Source text is empty or could not be chunked',
                'supporting_quotes': [],
                'error': 'No content to validate against'
            }

        relevant_chunks = self._retrieve_relevant_chunks(claim_text, chunks)
        if not relevant_chunks:
            return {
                'passed': False,
                'confidence': 0.0,
                'explanation': 'No relevant chunks found in source',
                'supporting_quotes': [],
                'error': 'Low similarity scores'
            }

        prompt = self._build_source_verification_prompt(claim_text, relevant_chunks)
        try:
            response = self.llm_client.call_llm(prompt, response_format="json")

            return {
                'passed': response.get('passed', False),
                'confidence': float(response.get('confidence', 0.5)),
                'explanation': response.get('explanation', 'No explanation provided'),
                'supporting_quotes': response.get('supporting_quotes', []),
                'error': None
            }

        except Exception as e:
            logger.error(f"Source-grounded LLM verification failed: {str(e)}")
            return {
                'passed': False,
                'confidence': 0.0,
                'explanation': f'LLM verification failed: {str(e)}',
                'supporting_quotes': [],
                'error': str(e)
            }

    def _split_into_chunks(self, text: str, chunk_size: int = 500) -> List[str]:
        """Split text into overlapping chunks for RAG retrieval."""
        if not text or len(text.strip()) == 0:
            return []

        sentences = text.replace('\n', ' ').split('. ')
        chunks: List[str] = []
        current_chunk: List[str] = []
        current_length = 0

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            sentence_length = len(sentence)

            if current_length + sentence_length > chunk_size and current_chunk:
                chunks.append('. '.join(current_chunk) + '.')
                current_chunk = [current_chunk[-1]] if current_chunk else []
                current_length = len(current_chunk[0]) if current_chunk else 0

            current_chunk.append(sentence)
            current_length += sentence_length

        if current_chunk:
            chunks.append('. '.join(current_chunk) + '.')

        return chunks

    def _retrieve_relevant_chunks(self, query: str, chunks: List[str]) -> List[Dict[str, Any]]:
        """Use TF-IDF similarity to retrieve relevant chunks for a claim."""
        if len(chunks) == 0:
            return []

        try:
            all_texts = [query] + chunks
            tfidf_matrix = self.vectorizer.fit_transform(all_texts)

            query_vector = tfidf_matrix[0:1]  # type: ignore
            chunk_vectors = tfidf_matrix[1:]  # type: ignore
            similarities = cosine_similarity(query_vector, chunk_vectors)[0]

            relevant_indices = []
            for idx, score in enumerate(similarities):
                if score >= RAG_SIMILARITY_THRESHOLD:
                    relevant_indices.append((idx, score))

            relevant_indices.sort(key=lambda x: x[1], reverse=True)
            relevant_indices = relevant_indices[:RAG_TOP_K]

            results = []
            for idx, score in relevant_indices:
                results.append({'text': chunks[idx], 'score': float(score)})

            return results

        except Exception as e:
            logger.error(f"RAG retrieval error: {str(e)}")
            return [{'text': chunk, 'score': 0.5} for chunk in chunks[:RAG_TOP_K]]

    def _build_source_verification_prompt(self, claim: str, chunks: List[Dict[str, Any]]) -> str:
        """Build source-grounded verification prompt."""
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
