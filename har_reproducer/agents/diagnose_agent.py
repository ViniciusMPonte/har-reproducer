import glob
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional

from ..models import Patch, FailureContext, FixExtractorPatch, PatchAction

if TYPE_CHECKING:
    from ..engine import Engine


class DiagnoseAgent:

    def __init__(self, engine: "Engine", failure_context: FailureContext) -> None:
        self.engine: Engine = engine
        self.context: FailureContext = failure_context
        self.history: List[str] = []

    def diagnose(self) -> Optional[Patch]:

        return self._simulate_diagnosis()

    def _simulate_diagnosis(self) -> Optional[Patch]:

        responses_dir: Path = self.engine.real_responses_dir
        for res_file in glob.glob(str(responses_dir / "res_*.json")):
            with open(res_file, "r") as f:
                content: str = f.read()
                if "eyJ" in content:  # JWT start
                    return FixExtractorPatch(
                        action=PatchAction.FIX_EXTRACTOR,
                        target_token_id="auth_token",
                        new_code=(
                            "def extract_auth_token(response): "
                            "import re; "
                            "m = re.search("
                            "r'eyJ[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+',"
                            " response['body']); "
                            "return m.group(0) if m else None"
                        ),
                        rationale="Found JWT in HTML response body"
                    )
        return None

    def read_step(self, index: int) -> str:

        return f"Step {index} data..."

    def grep_responses(self, pattern: str) -> List[str]:

        return [f"Found {pattern} in res_0001.json"]

    def get_session_state(self) -> str:

        return str(self.engine.session_store.state)
