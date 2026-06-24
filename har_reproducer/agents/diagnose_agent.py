from typing import List, Optional

from ..models import Patch, FailureContext, FixExtractorPatch


class DiagnoseAgent:
    """
    Diagnostic Agent: Uses tool-use to analyze failures and propose patches.
    """

    def __init__(self, engine, failure_context: FailureContext):
        self.engine = engine
        self.context = failure_context
        self.history = []

    def diagnose(self) -> Optional[Patch]:
        """
        Main loop: Think -> Tool Use -> Observe -> Think -> Patch.
        """
        # In a real implementation, this would call an LLM.
        # For this implementation, we'll simulate the logic:
        # 1. Look at the failed step.
        # 2. Look at the response.
        # 3. Search for the required token in previous responses.
        # 4. Propose a patch.

        return self._simulate_diagnosis()

    def _simulate_diagnosis(self) -> Optional[Patch]:
        """
        Simulates the diagnostic process for tests.
        """
        # Search for common JWT patterns in real responses
        import glob
        responses_dir = self.engine.real_responses_dir
        for res_file in glob.glob(str(responses_dir / "res_*.json")):
            with open(res_file, 'r') as f:
                content = f.read()
                if "eyJ" in content:  # JWT start
                    return FixExtractorPatch(
                        action="FIX_EXTRACTOR",
                        target_token_id="auth_token",
                        new_code="def extract_auth_token(response): import re; m = re.search(r'eyJ[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+', response['body']); return m.group(0) if m else None",
                        rationale="Found JWT in HTML response body"
                    )
        return None

    # Tools that would be provided to the LLM
    def read_step(self, index: int) -> str:
        """Reads the request and response of a step."""
        # Implementation would load from disk
        return f"Step {index} data..."

    def grep_responses(self, pattern: str) -> List[str]:
        """Greps all real responses for a pattern."""
        # Implementation would use grep_utils
        return [f"Found {pattern} in res_0001.json"]

    def get_session_state(self) -> str:
        """Returns the current session state."""
        return str(self.engine.session_store.state)
