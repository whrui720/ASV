"""LLM Verifier - Basic LLM plausibility check"""

import logging
from typing import Dict, Any
from hybrid_citation_scraper.llm_client import LLMClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class LLMVerifier:
    """Use LLM to perform basic plausibility check on claims"""
    
    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client
    
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
