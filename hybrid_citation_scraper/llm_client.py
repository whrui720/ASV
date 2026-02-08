"""LLM client for GPT-4o-mini interactions"""

import json
from typing import List, Dict, Any, Optional
from openai import OpenAI

from .config import OPENAI_API_KEY, CLAIM_EXTRACTION_MODEL, CLAIM_EXTRACTION_TEMPERATURE, ENABLE_COST_TRACKING
from models import ClaimObject, CitationDetails, LocationInText


class LLMClient:
    """Client for interacting with OpenAI API"""
    
    def __init__(self):
        self.client = OpenAI(api_key=OPENAI_API_KEY)
        self.model = CLAIM_EXTRACTION_MODEL
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        
    def extract_claims_from_chunk(
        self, 
        chunk_text: str, 
        chunk_id: int,
        available_citations: Optional[Dict[str, str]] = None,
        paper_title: Optional[str] = None,
        paper_abstract: Optional[str] = None
    ) -> List[ClaimObject]:
        """
        Extract claims from a text chunk using GPT-4o-mini.
        Returns list of ClaimObject instances.
        """
        citation_context = ""
        if available_citations:
            citation_list = "\n".join([f"{k}: {v[:100]}..." for k, v in list(available_citations.items())[:10]])
            citation_context = f"\n\nAvailable citations in this document:\n{citation_list}"
        
        paper_context = ""
        if paper_title or paper_abstract:
            paper_context = "\n\nPaper Context:"
            if paper_title:
                paper_context += f"\nTitle: {paper_title}"
            if paper_abstract:
                abstract_preview = paper_abstract[:400] + "..." if len(paper_abstract) > 400 else paper_abstract
                paper_context += f"\nAbstract: {abstract_preview}"
        
        prompt = f"""You are analyzing an academic text for claims. Extract ALL claims (both quantitative and qualitative) from the text below.

            IMPORTANT: Do NOT extract claims that are widely-known common knowledge or basic facts (e.g., "water boils at 100°C", "the Earth orbits the Sun", "DNA is a double helix"). Only extract claims that represent research findings, arguments, or assertions that would benefit from verification.

            For each claim, identify:
            1. The exact claim text
            2. Whether it's "quantitative" (involves numbers, statistics, measurements) or "qualitative" (descriptive, non-numerical)
            3. Any citation marker present (e.g., [1], (Smith, 2020), superscript numbers)
            4. Whether the claim is "original" - a direct conclusion or contribution from THIS paper (not citing external sources)

            Return a JSON array of claims with this exact structure:
            [
            {{
                "claim_text": "exact text of the claim",
                "claim_type": "quantitative or qualitative",
                "citation_marker": "[1] or null if no citation",
                "is_original": true or false
            }}
            ]

            Guidelines:
            - A quantitative claim mentions specific numbers, percentages, rates, statistics, or measurements
            - Include the full sentence containing the claim
            - If no citation marker is visible, set citation_marker to null
            - Set is_original to true ONLY if: (a) no external citation is present AND (b) the claim is a conclusion/finding from THIS paper's own work, figures, tables, or experiments (considering the paper's title and abstract for context)
            - Set is_original to false if the claim cites external sources, even if discussing the paper's own work
            - ONLY extract objective, fact-based claims - do NOT include subjective opinions, interpretations, or qualitative judgments
            - SKIP claims that are common knowledge - do not include them in the output at all
            - SKIP claims that are subjective opinions (e.g., "This approach is promising", "The results are interesting")
            - Be thorough - extract all non-trivial, objective claims, not just the most prominent ones
            {paper_context}
            {citation_context}

            Text to analyze:
            {chunk_text}

            Return only the JSON array, no additional text."""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a precise academic text analyzer that extracts claims and citations. Always return valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=CLAIM_EXTRACTION_TEMPERATURE,
                response_format={"type": "json_object"}
            )
            
            # Track token usage
            if ENABLE_COST_TRACKING and response.usage:
                self.total_input_tokens += response.usage.prompt_tokens
                self.total_output_tokens += response.usage.completion_tokens
            
            # Parse response
            content = response.choices[0].message.content
            if not content:
                return []
            
            result = json.loads(content)
            
            # Handle both {"claims": [...]} and direct array formats
            claims_data = result.get("claims", result) if isinstance(result, dict) else result
            
            # Convert to ClaimObject instances
            claims = []
            for idx, claim_data in enumerate(claims_data):
                claim_id = f"claim_{chunk_id}_{idx}"
                
                claim = ClaimObject(
                    claim_id=claim_id,
                    text=claim_data.get("claim_text", ""),
                    claim_type=claim_data.get("claim_type", "qualitative"),
                    citation_found=claim_data.get("citation_marker") is not None,
                    citation_text=claim_data.get("citation_marker"),
                    citation_details=None,  # Will be populated later
                    is_original=claim_data.get("is_original", False),
                    location_in_text=LocationInText(
                        start=0,  # Would need more sophisticated tracking
                        end=0,
                        chunk_id=chunk_id
                    )
                )
                claims.append(claim)
            
            return claims
            
        except Exception as e:
            print(f"Error extracting claims from chunk {chunk_id}: {e}")
            return []
    
    def parse_references_with_llm(self, ref_section: str) -> Dict[str, str]:
        """
        Parse reference section using LLM when deterministic parsing fails.
        Returns dict mapping citation_id -> citation_text
        """
        prompt = f"""Parse this reference section and extract all citations.

            Return a JSON object where keys are citation identifiers (numbers for numeric citations, or author names for author-year citations) and values are the full citation text.

            Example output format:
            {{
            "1": "Smith, J., & Jones, M. (2020). Title of paper. Journal Name, 10(2), 123-145.",
            "2": "Brown, A. et al. (2019). Another paper title. Conference Proceedings, 456-789."
            }}

            Reference section:
            {ref_section}

            Return only the JSON object, no additional text."""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a citation parser that extracts structured information from reference sections. Always return valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                response_format={"type": "json_object"}
            )
            
            if ENABLE_COST_TRACKING and response.usage:
                self.total_input_tokens += response.usage.prompt_tokens
                self.total_output_tokens += response.usage.completion_tokens
            
            content = response.choices[0].message.content
            if not content:
                return {}
            
            result = json.loads(content)
            
            # Handle wrapped format
            if "citations" in result:
                return result["citations"]
            return result
            
        except Exception as e:
            print(f"Error parsing references with LLM: {e}")
            return {}
    
    def call_llm(self, prompt: str, response_format: str = "json") -> Any:
        """
        Generic LLM call method for validator and other modules.
        
        Args:
            prompt: The prompt to send to the LLM
            response_format: "json" for JSON response, "text" for plain text
            
        Returns:
            Parsed JSON dict if response_format="json", raw text otherwise
        """
        try:
            if response_format == "json":
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.2,
                    response_format={"type": "json_object"}
                )
            else:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.2
                )
            
            # Track tokens
            if ENABLE_COST_TRACKING and response.usage:
                self.total_input_tokens += response.usage.prompt_tokens
                self.total_output_tokens += response.usage.completion_tokens
            
            content = response.choices[0].message.content
            
            if response_format == "json":
                return json.loads(content or "{}")
            else:
                return content or ""
        
        except Exception as e:
            print(f"Error in LLM call: {e}")
            if response_format == "json":
                return {}
            else:
                return ""
    
    def get_cost_summary(self) -> Dict[str, float]:
        """
        Calculate total cost based on token usage.
        GPT-4o-mini pricing: $0.150/M input tokens, $0.600/M output tokens
        """
        input_cost = (self.total_input_tokens / 1_000_000) * 0.150
        output_cost = (self.total_output_tokens / 1_000_000) * 0.600
        total_cost = input_cost + output_cost
        
        return {
            "input_tokens": self.total_input_tokens,
            "output_tokens": self.total_output_tokens,
            "total_tokens": self.total_input_tokens + self.total_output_tokens,
            "input_cost": input_cost,
            "output_cost": output_cost,
            "total_cost": total_cost
        }
