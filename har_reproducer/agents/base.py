from typing import Optional

class BaseAgent:
    """
    Base class for all Token Extraction Agents.
    Implements the TDD loop for verified extractor generation.
    """
    def __init__(self, token_id: str, response_sample: dict, expected_value: str):
        # Normalize token_id to be a valid Python identifier for the function name
        self.token_id = token_id
        self.safe_token_id = token_id.replace("-", "_").replace(".", "_").replace(" ", "_")
        self.response_sample = response_sample
        self.expected_value = expected_value

    def generate_code(self) -> str:
        """
        To be implemented by subclasses. 
        Should return the Python source code for the extractor function.
        """
        raise NotImplementedError("Subclasses must implement generate_code")

    def run_tdd_loop(self, max_attempts: int = 5, origin_step: Optional[int] = None):
        """
        Runs the TDD loop: generate -> test -> fix -> repeat.
        """
        for attempt in range(max_attempts):
            code = self.generate_code()
            
            if self._verify_code(code):
                from har_reproducer.models import Extractor
                return Extractor(
                    token_id=self.token_id,
                    code=code,
                    verified=True,
                    agent_type=self.__class__.__name__,
                    origin_step=origin_step
                )
            
            print(f"Attempt {attempt + 1} failed for {self.token_id}. Retrying...")
            
        return None

    def _verify_code(self, code: str) -> bool:
        """
        Verifies the generated code by executing it against the response sample.
        """
        import subprocess
        import sys
        from pathlib import Path
        
        temp_file = Path(f"temp_extractor_{self.token_id}.py")
        
        wrapped_code = f"""
import sys
import json
from typing import Dict
class ExtractorError(Exception): pass

{code}

if __name__ == "__main__":
    response = {self.response_sample}
    try:
        # Call the function directly by name
        result = extract_{self.safe_token_id}(response)
        print(result)
    except Exception as e:
        print(f"ERROR: {{e}}", file=sys.stderr)
        sys.exit(1)
"""
        temp_file.write_text(wrapped_code)
        
        try:
            result = subprocess.run(
                [sys.executable, str(temp_file)],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0 and result.stdout.strip() == self.expected_value:
                return True
        except subprocess.TimeoutExpired:
            pass
        finally:
            if temp_file.exists():
                temp_file.unlink()
                
        return False
