"""
Truth Table Checker - Query truth databases for qualitative subjective claims without citations

Queries fact-checking databases and APIs to validate claims without clear citations.
Uses Google Fact Check Tools API, ClaimReview schema, and other truth databases.
"""

import os
import json
import logging
from typing import Dict, Any, Optional, List
import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TruthTableChecker:
    """
    Queries truth tables and fact-checking databases for claims without citations.
    
    Sources:
    - Google Fact Check Tools API
    - ClaimReview Schema
    - International Fact-Checking Network (IFCN)
    - Manual fact-checking database
    """
    
    def __init__(self, llm_client=None):
        """
        Initialize truth table checker.
        
        Args:
            llm_client: Optional LLMClient for LLM-powered fallback search
        """
        self.llm_client = llm_client
        self.google_api_key = os.getenv('GOOGLE_API_KEY') or os.getenv('GOOGLE_FACT_CHECK_KEY')
        self.session = requests.Session()
    
    def check_claim(self, claim_text: str) -> Dict[str, Any]:
        """
        Check a claim against truth tables and fact-checking databases.
        
        Args:
            claim_text: The claim to verify
            
        Returns:
            Dict with verification results:
            {
                'found': bool,
                'rating': str,  # 'true', 'false', 'mixed', 'unverified'
                'confidence': float,
                'sources': List[Dict],  # Fact-check sources
                'explanation': str,
                'method': str  # 'truth_table', 'llm_search', 'not_found'
            }
        """
        logger.info(f"Checking claim: {claim_text[:100]}...")
        
        # Step 1: Query Google Fact Check API
        if self.google_api_key:
            result = self._query_google_fact_check(claim_text)
            if result['found']:
                result['method'] = 'truth_table'
                return result
        
        # Step 2: Try ClaimReview structured data search
        result = self._search_claimreview(claim_text)
        if result['found']:
            result['method'] = 'truth_table'
            return result
        
        # Step 3: Fallback to LLM search with forced sources
        if self.llm_client:
            logger.info("Truth table lookup failed, trying LLM search...")
            result = self._llm_fact_check(claim_text)
            if result['found']:
                result['method'] = 'llm_search'
                return result
        
        # No verification found
        return {
            'found': False,
            'rating': 'unverified',
            'confidence': 0.0,
            'sources': [],
            'explanation': 'No fact-check information found for this claim.',
            'method': 'not_found'
        }
    
    def _query_google_fact_check(self, claim_text: str) -> Dict[str, Any]:
        """
        Query Google Fact Check Tools API.
        
        API docs: https://developers.google.com/fact-check/tools/api
        """
        if not self.google_api_key:
            return {'found': False}
        
        try:
            url = "https://factchecktools.googleapis.com/v1alpha1/claims:search"
            params = {
                'query': claim_text,
                'key': self.google_api_key,
                'languageCode': 'en'
            }
            
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            if not data.get('claims'):
                logger.info("No results from Google Fact Check API")
                return {'found': False}
            
            # Process first matching claim
            claim_review = data['claims'][0]
            
            # Extract rating
            rating_text = claim_review.get('claimReview', [{}])[0].get('textualRating', '').lower()
            rating = self._normalize_rating(rating_text)
            
            # Build sources list
            sources = []
            for review in claim_review.get('claimReview', []):
                sources.append({
                    'publisher': review.get('publisher', {}).get('name', 'Unknown'),
                    'url': review.get('url', ''),
                    'rating': review.get('textualRating', ''),
                    'title': review.get('title', '')
                })
            
            result = {
                'found': True,
                'rating': rating,
                'confidence': 0.9,  # High confidence for verified fact-check sources
                'sources': sources,
                'explanation': claim_review.get('text', claim_text)
            }
            
            logger.info(f"✓ Found fact-check: {rating}")
            return result
            
        except requests.exceptions.RequestException as e:
            logger.warning(f"Google Fact Check API error: {str(e)}")
            return {'found': False}
        except Exception as e:
            logger.warning(f"Error processing fact-check results: {str(e)}")
            return {'found': False}
    
    def _search_claimreview(self, claim_text: str) -> Dict[str, Any]:
        """
        Search for ClaimReview structured data via web search.
        
        This is a placeholder for potential implementation using
        web scraping or Google Custom Search API.
        """
        # Placeholder - would require web scraping or Custom Search API
        logger.info("ClaimReview search not yet implemented")
        return {'found': False}
    
    def _llm_fact_check(self, claim_text: str) -> Dict[str, Any]:
        """
        Use LLM to search for fact-checks with forced source citations.
        
        This is a fallback when truth tables don't have the claim.
        """
        if not self.llm_client:
            return {'found': False}
        
        try:
            prompt = f"""You are a fact-checking assistant. Research this claim and provide a verdict.

Claim: "{claim_text}"

Search for fact-checks from reputable sources (Snopes, PolitiFact, FactCheck.org, etc.).
If you cannot find specific fact-checks, use general knowledge but be conservative.

Respond in JSON format:
{{
    "found": true/false,
    "rating": "true" | "false" | "mixed" | "unverified",
    "confidence": 0.0-1.0,
    "sources": [
        {{
            "publisher": "Source Name",
            "url": "URL if available",
            "rating": "Their rating",
            "title": "Article title"
        }}
    ],
    "explanation": "Brief explanation of the verdict"
}}

If you cannot verify the claim, set found=false and rating="unverified"."""
            
            response = self.llm_client.call_llm(
                prompt=prompt,
                system_message="You are a rigorous fact-checker. Only cite claims you can verify from reliable sources.",
                model="gpt-4o-mini",
                response_format={"type": "json_object"}
            )
            
            result = json.loads(response)
            
            # Lower confidence for LLM-based checks
            if result.get('found') and result.get('confidence', 0) > 0.5:
                result['confidence'] = min(result['confidence'], 0.7)
                logger.info(f"✓ LLM fact-check: {result.get('rating')}")
            
            return result
            
        except Exception as e:
            logger.warning(f"LLM fact-check failed: {str(e)}")
            return {'found': False}
    
    def _normalize_rating(self, rating_text: str) -> str:
        """
        Normalize various fact-check ratings to standard values.
        
        Returns: 'true', 'false', 'mixed', 'unverified'
        """
        rating_lower = rating_text.lower()
        
        # True ratings
        if any(word in rating_lower for word in ['true', 'correct', 'accurate', 'verified']):
            if any(word in rating_lower for word in ['mostly', 'partially', 'mixture']):
                return 'mixed'
            return 'true'
        
        # False ratings
        if any(word in rating_lower for word in ['false', 'incorrect', 'inaccurate', 'pants on fire', 'debunked']):
            if any(word in rating_lower for word in ['mostly', 'partially']):
                return 'mixed'
            return 'false'
        
        # Mixed ratings
        if any(word in rating_lower for word in ['mixed', 'half', 'partially', 'mostly']):
            return 'mixed'
        
        # Unknown
        return 'unverified'
    
    def format_for_report(self, check_result: Dict[str, Any], claim_text: str) -> Optional[Dict[str, Any]]:
        """
        Format truth table result for inclusion in final report.
        
        Returns a judgment-like object that can be displayed in Step 4, or None if not found.
        """
        if not check_result['found']:
            return None
        
        # Map rating to factual assessment
        is_factual = check_result['rating'] in ['true', 'mixed']
        is_appropriate = check_result['rating'] == 'true'
        
        return {
            'claim_id': None,  # Will be set by caller
            'validation_type': 'qualitative_truth_table',
            'validation_code': None,
            'result': {
                'is_factual': is_factual,
                'is_appropriate': is_appropriate,
                'explanation': check_result['explanation']
            },
            'confidence_score': check_result['confidence'],
            'validation_metadata': {
                'checked_by': check_result['method'],
                'sources': check_result['sources']
            }
        }
