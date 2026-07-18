import subprocess
import sys
from pathlib import Path
from subprocess import CompletedProcess
from typing import Any, Dict, Optional, Tuple

from har_reproducer.models import AgentType, Extractor


class BaseAgent:
    """
    Base class for all Token Extraction Agents.
    Implements the TDD loop for verified extractor generation.
    """

    def __init__(self, token_id: str, response_sample: Dict[str, Any], expected_value: str) -> None:
        self.token_id: str = token_id
        self.safe_token_id: str = token_id
        self.response_sample: dict[str, Any] = response_sample
        self.expected_value: str = expected_value

    def generate_code(self, last_error: Optional[str] = None) -> str:
        """
        To be implemented by subclasses.
        Should return the Python source code for the extractor function.
        """
        raise NotImplementedError("Subclasses must implement generate_code")

    def run_tdd_loop(self, max_attempts: int = 5, origin_step: Optional[int] = None) -> Optional[Extractor]:
        """
        Runs the TDD loop: generate -> test -> fix -> repeat.
        """
        last_error: Optional[str] = None
        for attempt in range(max_attempts):
            code: str = self.generate_code(last_error=last_error)

            success: bool
            error: Optional[str]
            success, error = self._verify_code(code)

            if success:
                return Extractor(
                    token_id=self.token_id,
                    code=code,
                    verified=True,
                    agent_type=AgentType(self.__class__.__name__),
                    origin_step=origin_step
                )

            last_error = error
            print(f"Attempt {attempt + 1} failed for {self.token_id}. Retrying...")

        return None

    def _verify_code(self, code: str) -> Tuple[bool, Optional[str]]:
        """
        Verifies the generated code by executing it against the response sample.
        Returns a tuple of (success, error_message).
        """
        script_path: Path = self._write_temp_script(code)
        try:
            return self._execute_script(script_path)
        finally:
            self._cleanup_script(script_path)

    def _write_temp_script(self, code: str) -> Path:
        """Wraps the extractor code in a runnable script and writes it to a temp file."""
        temp_file: Path = Path(f"temp_extractor_{self.token_id}.py")
        wrapped_code: str = f"""
import sys
import json
from typing import Dict
class ExtractorError(Exception): pass

{code}

if __name__ == "__main__":
    response = {self.response_sample}
    try:
        result = extract_{self.safe_token_id}(response)
        print(result)
    except Exception as e:
        print(f"ERROR: {{e}}", file=sys.stderr)
        sys.exit(1)
"""
        temp_file.write_text(wrapped_code)
        return temp_file

    def _execute_script(self, script_path: Path) -> Tuple[bool, Optional[str]]:
        """Runs the temp script and checks whether its output matches the expected value."""
        try:
            result: CompletedProcess[str] = subprocess.run(
                [sys.executable, str(script_path)],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except subprocess.TimeoutExpired:
            print(f"[AVISO] Timeout ao verificar extrator para {self.token_id}")
            return False, "Timeout during verification"

        if result.returncode == 0 and result.stdout.strip() == self.expected_value:
            return True, None

        error: str = result.stderr.strip() or (
            f"Output mismatch: got {result.stdout.strip()!r}, expected {self.expected_value!r}"
        )
        return False, error

    def _cleanup_script(self, script_path: Path) -> None:
        """Removes the temporary script file if it exists."""
        if script_path.exists():
            script_path.unlink()
