"""Truth Table Checker - Query Google Fact Check API and ClaimReview schema"""

import requests
import logging
from typing import Dict, Any, List
from .config import GOOGLE_FACT_CHECK_API_KEY, TRUTH_TABLE_CONFIDENCE_THRESHOLD

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TruthTableChecker:
    """Check claims against Google Fact Check API"""
    
    def __init__(self, api_key: str = GOOGLE_FACT_CHECK_API_KEY):
        self.api_key = api_key
        self.base_url = "https://factchecktools.googleapis.com/v1alpha1/claims:search"
    
    def check_claim(self, claim_text: str) -> Dict[str, Any]:
        """
        Check if claim appears in Google Fact Check API.
        Returns dict with 'found', 'confidence', 'explanation', and 'sources'.
        """
        if not self.api_key:
            logger.warning("No API key provided for Google Fact Check")
            return {
                'found': False,
                'confidence': 0.0,
                'explanation': 'No API key configured',
                'sources': []
            }
        
        try:
            params = {
                'query': claim_text[:512],  # API has character limits
                'key': self.api_key,
                'languageCode': 'en'
            }
            
            response = requests.get(self.base_url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            if 'claims' not in data or len(data['claims']) == 0:
                return {
                    'found': False,
                    'confidence': 0.0,
                    'explanation': 'No matching fact checks found',
                    'sources': []
                }
            
            # Process claims
            best_match = self._find_best_match(data['claims'], claim_text)
            
            if not best_match:
                return {
                    'found': False,
                    'confidence': 0.0,
                    'explanation': 'No relevant matches found',
                    'sources': []
                }
            
            # Extract information
            claim_review = best_match.get('claimReview', [])
            if claim_review:
                review = claim_review[0]
                rating = review.get('textualRating', 'Unknown')
                publisher = review.get('publisher', {}).get('name', 'Unknown')
                url = review.get('url', '')
                
                # Determine if rating supports the claim
                passed = self._interpret_rating(rating)
                confidence = self._calculate_confidence(rating, best_match.get('similarity', 0.7))
                
                return {
                    'found': True,
                    'confidence': confidence,
                    'explanation': f"Fact check found: '{rating}' by {publisher}",
                    'sources': [url] if url else []
                }
            
            return {
                'found': False,
                'confidence': 0.0,
                'explanation': 'Claim found but no review available',
                'sources': []
            }
        
        except requests.exceptions.RequestException as e:
            logger.error(f"API request failed: {str(e)}")
            return {
                'found': False,
                'confidence': 0.0,
                'explanation': f'API error: {str(e)}',
                'sources': []
            }
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            return {
                'found': False,
                'confidence': 0.0,
                'explanation': f'Error: {str(e)}',
                'sources': []
            }
    
    def _find_best_match(self, claims: List[Dict], query: str) -> Dict:
        """Find the claim that best matches the query"""
        # For now, just return the first claim
        # In a more sophisticated version, calculate similarity scores
        if claims:
            claim = claims[0]
            # Add a pseudo similarity score
            claim['similarity'] = 0.8
            return claim
        return {}
    
    def _interpret_rating(self, rating: str) -> bool:
        """Interpret textual rating to determine if claim passes"""
        rating_lower = rating.lower()
        
        # Positive ratings
        positive_keywords = ['true', 'correct', 'accurate', 'verified', 'confirmed', 'mostly true']
        if any(keyword in rating_lower for keyword in positive_keywords):
            return True
        
        # Negative ratings
        negative_keywords = ['false', 'incorrect', 'inaccurate', 'misleading', 'debunked', 'unproven']
        if any(keyword in rating_lower for keyword in negative_keywords):
            return False
        
        # Mixed/uncertain ratings - default to False for safety
        return False
    
    def _calculate_confidence(self, rating: str, similarity: float) -> float:
        """Calculate confidence score based on rating clarity and similarity"""
        rating_lower = rating.lower()
        
        # High confidence ratings
        if any(word in rating_lower for word in ['true', 'false', 'correct', 'incorrect']):
            base_confidence = 0.9
        # Medium confidence ratings
        elif any(word in rating_lower for word in ['mostly', 'partly', 'somewhat']):
            base_confidence = 0.6
        # Low confidence ratings
        else:
            base_confidence = 0.4
        
        # Adjust by similarity
        final_confidence = base_confidence * similarity
        
        return min(final_confidence, 1.0)
