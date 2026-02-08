"""Quantitative Validator - Generate and execute Python scripts for dataset validation"""

import os
import subprocess
import tempfile
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from hybrid_citation_scraper.llm_client import LLMClient
from models import ClaimObject, ValidationResult

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class QuantitativeValidator:
    """Generate Python scripts and validate quantitative claims against datasets"""
    
    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client
        self.script_dir = Path("generated_scripts")
        self.script_dir.mkdir(exist_ok=True)
    
    def validate_claim(self, claim: ClaimObject, dataset_path: str) -> ValidationResult:
        """
        Validate a quantitative claim by generating and executing a Python script.
        Consolidates logic from scriptgen.py and runner.py.
        """
        logger.info(f"Validating quantitative claim: {claim.claim_id}")
        
        try:
            # Step 1: Generate validation script
            script_code = self._generate_script(claim.text, dataset_path)
            
            if not script_code:
                return ValidationResult(
                    claim_id=claim.claim_id,
                    claim_type=claim.claim_type,
                    originally_uncited=claim.originally_uncited,
                    validated=False,
                    validation_method="python_script",
                    confidence=0.0,
                    passed=False,
                    explanation="Failed to generate validation script",
                    sources_used=[dataset_path],
                    errors="Script generation failed"
                )
            
            # Step 2: Save script to file
            script_path = self.script_dir / f"validate_{claim.claim_id}.py"
            with open(script_path, 'w', encoding='utf-8') as f:
                f.write(script_code)
            
            logger.info(f"  Generated script: {script_path}")
            
            # Step 3: Execute script
            execution_result = self._execute_script(script_path)
            
            # Step 4: Parse results
            return self._parse_execution_result(
                claim,
                dataset_path,
                execution_result
            )
        
        except Exception as e:
            logger.error(f"Validation error: {str(e)}")
            return ValidationResult(
                claim_id=claim.claim_id,
                claim_type=claim.claim_type,
                originally_uncited=claim.originally_uncited,
                validated=False,
                validation_method="python_script",
                confidence=0.0,
                passed=False,
                explanation="Validation error occurred",
                sources_used=[dataset_path],
                errors=str(e)
            )
    
    def _generate_script(self, claim_text: str, dataset_path: str) -> Optional[str]:
        """Generate Python script to validate claim against dataset"""
        prompt = self._build_script_generation_prompt(claim_text, dataset_path)
        
        try:
            response = self.llm_client.call_llm(prompt, response_format="text")
            
            # Extract Python code from response
            code = self._extract_code(response)
            return code
        
        except Exception as e:
            logger.error(f"Script generation failed: {str(e)}")
            return None
    
    def _build_script_generation_prompt(self, claim_text: str, dataset_path: str) -> str:
        """Build prompt for script generation"""
        return f"""You are a Python code generator for data validation. Generate a complete, executable Python script to validate a quantitative claim against a dataset.

Claim: "{claim_text}"
Dataset path: "{dataset_path}"

Requirements:
1. Load the dataset (detect format: CSV, JSON, Excel)
2. Extract relevant numeric values to verify the claim
3. Perform calculations/comparisons as needed
4. Print results in this exact JSON format:
   {{"passed": true/false, "confidence": 0.0-1.0, "explanation": "brief explanation"}}

Important guidelines:
- Use pandas for data loading (pd.read_csv, pd.read_json, pd.read_excel)
- Handle missing values and data quality issues
- Be precise with numeric comparisons (consider rounding, tolerance)
- If claim mentions percentage, verify the calculation
- If claim mentions comparison (greater/less), verify it
- confidence should reflect data quality and match precision
- Wrap the final output in a try-except block
- Import json module and use json.dumps() for output

Example output format:
import json
result = {{"passed": True, "confidence": 0.95, "explanation": "Dataset confirms claim within tolerance"}}
print(json.dumps(result))

Generate ONLY the Python code, no explanations or markdown formatting.
"""
    
    def _extract_code(self, response: str) -> str:
        """Extract Python code from LLM response"""
        # Remove markdown code blocks if present
        if "```python" in response:
            start = response.index("```python") + len("```python")
            end = response.rindex("```")
            return response[start:end].strip()
        elif "```" in response:
            start = response.index("```") + len("```")
            end = response.rindex("```")
            return response[start:end].strip()
        else:
            return response.strip()
    
    def _execute_script(self, script_path: Path) -> Dict[str, Any]:
        """Execute the generated Python script and capture output"""
        try:
            # Execute with timeout
            result = subprocess.run(
                ['python', str(script_path)],
                capture_output=True,
                text=True,
                timeout=30,  # 30 second timeout
                cwd=script_path.parent
            )
            
            return {
                'success': result.returncode == 0,
                'stdout': result.stdout,
                'stderr': result.stderr,
                'returncode': result.returncode
            }
        
        except subprocess.TimeoutExpired:
            return {
                'success': False,
                'stdout': '',
                'stderr': 'Script execution timed out (30s limit)',
                'returncode': -1
            }
        except Exception as e:
            return {
                'success': False,
                'stdout': '',
                'stderr': str(e),
                'returncode': -1
            }
    
    def _parse_execution_result(
        self,
        claim: ClaimObject,
        dataset_path: str,
        execution_result: Dict[str, Any]
    ) -> ValidationResult:
        """Parse script execution results into ValidationResult"""
        
        if not execution_result['success']:
            return ValidationResult(
                claim_id=claim.claim_id,
                claim_type=claim.claim_type,
                originally_uncited=claim.originally_uncited,
                validated=False,
                validation_method="python_script",
                confidence=0.0,
                passed=False,
                explanation="Script execution failed",
                sources_used=[dataset_path],
                errors=execution_result['stderr']
            )
        
        # Parse JSON output from stdout
        try:
            import json
            output = execution_result['stdout'].strip()
            
            # Find JSON in output
            if '{' in output:
                json_start = output.index('{')
                json_end = output.rindex('}') + 1
                json_str = output[json_start:json_end]
                result_data = json.loads(json_str)
            else:
                raise ValueError("No JSON output found")
            
            passed = result_data.get('passed', False)
            confidence = float(result_data.get('confidence', 0.5))
            explanation = result_data.get('explanation', 'No explanation provided')
            
            return ValidationResult(
                claim_id=claim.claim_id,
                claim_type=claim.claim_type,
                originally_uncited=claim.originally_uncited,
                validated=True,
                validation_method="python_script",
                confidence=confidence,
                passed=passed,
                explanation=explanation,
                sources_used=[dataset_path],
                errors=None
            )
        
        except Exception as e:
            return ValidationResult(
                claim_id=claim.claim_id,
                claim_type=claim.claim_type,
                originally_uncited=claim.originally_uncited,
                validated=False,
                validation_method="python_script",
                confidence=0.0,
                passed=False,
                explanation="Failed to parse script output",
                sources_used=[dataset_path],
                errors=f"Parse error: {str(e)}. Output: {execution_result['stdout']}"
            )
