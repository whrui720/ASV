"""
Dataset Searcher - Find data sources for quantitative claims without citations

Uses LLM-powered search to find relevant datasets when no citation is provided.
Integrates with Google Dataset Search, Kaggle, and other data repositories.
"""

import os
import json
import logging
from typing import List, Dict, Any, Optional
from pathlib import Path
import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DatasetSearcher:
    """
    Search for datasets when no citation is provided for quantitative claims.
    
    Uses:
    - LLM to generate search queries
    - Google Dataset Search API
    - Data repository APIs (Kaggle, data.gov, etc.)
    - Web scraping as fallback
    """
    
    def __init__(self, llm_client=None):
        """
        Initialize dataset searcher.
        
        Args:
            llm_client: LLMClient instance from hybrid_citation_scraper
        """
        self.llm_client = llm_client
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    def search_datasets(self, claim_text: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        Search for datasets relevant to a claim.
        
        Args:
            claim_text: The text of the quantitative claim
            top_k: Number of top results to return
            
        Returns:
            List of dataset candidates with metadata:
            [
                {
                    'title': str,
                    'url': str,
                    'source': str,  # 'kaggle', 'data.gov', etc.
                    'description': str,
                    'relevance_score': float,
                    'format': str  # 'csv', 'json', etc.
                }
            ]
        """
        logger.info(f"Searching datasets for claim: {claim_text[:100]}...")
        
        # Generate search queries using LLM
        search_queries = self._generate_search_queries(claim_text)
        
        all_results = []
        
        # Search across multiple sources
        for query in search_queries:
            # Search data.gov
            results = self._search_data_gov(query)
            all_results.extend(results)
            
            # Search Kaggle (requires API key)
            if os.getenv('KAGGLE_USERNAME'):
                results = self._search_kaggle(query)
                all_results.extend(results)
            
            # Google Dataset Search (basic implementation)
            results = self._search_google_datasets(query)
            all_results.extend(results)
        
        # Rank results by relevance using LLM
        ranked_results = self._rank_results(claim_text, all_results)
        
        return ranked_results[:top_k]
    
    def _generate_search_queries(self, claim_text: str) -> List[str]:
        """
        Generate search queries from claim text using LLM.
        
        Returns list of search queries optimized for dataset discovery.
        """
        if not self.llm_client:
            # Fallback: use claim text as-is
            return [claim_text]
        
        prompt = f"""Given this quantitative claim, generate 2-3 search queries to find relevant datasets.
Focus on the key statistical concepts, time periods, and entities mentioned.

Claim: "{claim_text}"

Return only a JSON array of search queries:
["query 1", "query 2", "query 3"]"""
        
        try:
            response = self.llm_client.call_llm(
                prompt=prompt,
                system_message="You are a dataset search expert. Generate precise search queries for finding statistical datasets.",
                model="gpt-4o-mini",
                response_format={"type": "json_object"}
            )
            
            result = json.loads(response)
            queries = result.get('queries', [claim_text])
            logger.info(f"Generated {len(queries)} search queries")
            return queries
            
        except Exception as e:
            logger.warning(f"Query generation failed: {str(e)}, using claim text")
            return [claim_text]
    
    def _search_data_gov(self, query: str) -> List[Dict[str, Any]]:
        """
        Search data.gov using their API.
        
        API docs: https://www.data.gov/developers/apis
        """
        try:
            url = "https://catalog.data.gov/api/3/action/package_search"
            params = {
                'q': query,
                'rows': 10,
                'sort': 'score desc'
            }
            
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            results = []
            
            if data.get('success') and data.get('result', {}).get('results'):
                for item in data['result']['results']:
                    # Find CSV or JSON resources
                    for resource in item.get('resources', []):
                        if resource.get('format', '').lower() in ['csv', 'json', 'xlsx']:
                            results.append({
                                'title': item.get('title', 'Untitled'),
                                'url': resource.get('url', ''),
                                'source': 'data.gov',
                                'description': item.get('notes', '')[:200],
                                'format': resource.get('format', '').lower(),
                                'relevance_score': 0.0  # Will be scored later
                            })
                            break  # One resource per dataset
            
            logger.info(f"Found {len(results)} results from data.gov")
            return results
            
        except Exception as e:
            logger.warning(f"data.gov search failed: {str(e)}")
            return []
    
    def _search_kaggle(self, query: str) -> List[Dict[str, Any]]:
        """
        Search Kaggle datasets.
        
        Requires KAGGLE_USERNAME and KAGGLE_KEY environment variables.
        """
        try:
            from kaggle.api.kaggle_api_extended import KaggleApi
            
            api = KaggleApi()
            api.authenticate()
            
            datasets = api.dataset_list(search=query, page=1)
            
            results = []
            for dataset in datasets[:5]:
                # Safely extract dataset attributes with fallbacks
                ref = getattr(dataset, 'ref', 'unknown/dataset')
                title = ref.split('/')[-1].replace('-', ' ').title()
                description = getattr(dataset, 'subtitle', '') or getattr(dataset, 'description', '')
                
                results.append({
                    'title': title,
                    'url': f"https://www.kaggle.com/datasets/{ref}",
                    'source': 'kaggle',
                    'description': description,
                    'format': 'csv',  # Kaggle typically uses CSV
                    'relevance_score': 0.0
                })
            
            logger.info(f"Found {len(results)} results from Kaggle")
            return results
            
        except ImportError:
            logger.warning("Kaggle API not installed (pip install kaggle)")
            return []
        except Exception as e:
            logger.warning(f"Kaggle search failed: {str(e)}")
            return []
    
    def _search_google_datasets(self, query: str) -> List[Dict[str, Any]]:
        """
        Search Google Dataset Search.
        
        Note: Google Dataset Search API is not publicly available.
        This is a placeholder for future implementation or web scraping.
        """
        # Placeholder - would require web scraping or API access
        logger.info("Google Dataset Search not yet implemented")
        return []
    
    def _rank_results(self, claim_text: str, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Rank search results by relevance to the claim using LLM.
        
        Returns sorted list with relevance_score updated.
        """
        if not results:
            return []
        
        if not self.llm_client:
            # No ranking, return as-is
            return results
        
        try:
            # Create a prompt with claim and results
            results_text = "\n\n".join([
                f"Dataset {i+1}:\nTitle: {r['title']}\nDescription: {r['description']}"
                for i, r in enumerate(results[:10])  # Limit to 10 for LLM context
            ])
            
            prompt = f"""Rank these datasets by relevance to the following claim.
Rate each dataset from 0.0 (not relevant) to 1.0 (highly relevant).

Claim: "{claim_text}"

Datasets:
{results_text}

Return JSON with rankings:
{{"rankings": [{{"dataset_id": 1, "score": 0.85}}, ...]}}"""
            
            response = self.llm_client.call_llm(
                prompt=prompt,
                system_message="You are a data relevance expert. Accurately assess dataset relevance to claims.",
                model="gpt-4o-mini",
                response_format={"type": "json_object"}
            )
            
            ranking_data = json.loads(response)
            rankings = {r['dataset_id']: r['score'] for r in ranking_data.get('rankings', [])}
            
            # Update scores
            for i, result in enumerate(results[:10]):
                result['relevance_score'] = rankings.get(i + 1, 0.0)
            
            # Sort by score
            results.sort(key=lambda x: x.get('relevance_score', 0.0), reverse=True)
            
            logger.info(f"Ranked {len(results)} results")
            return results
            
        except Exception as e:
            logger.warning(f"Result ranking failed: {str(e)}")
            return results
    
    def get_best_match(self, claim_text: str) -> Optional[Dict[str, Any]]:
        """
        Get the single best dataset match for a claim.
        
        Returns the highest-ranked dataset or None if no good matches found.
        """
        results = self.search_datasets(claim_text, top_k=1)
        
        if results and results[0].get('relevance_score', 0) > 0.5:
            return results[0]
        
        return None
