from typing import Any, Dict


class ExtractorTemplate:

    @staticmethod
    def render_temp_script(
            safe_token_id: str,
            code: str,
            response_sample: Dict[str, Any],
    ) -> str:
        return f"""
import sys
import json
from typing import Dict
class ExtractorError(Exception): pass

{code}

if __name__ == "__main__":
    response = {response_sample!r}
    try:
        result = extract_{safe_token_id}(response)
        print(result)
    except Exception as e:
        print(f"ERROR: {{e}}", file=sys.stderr)
        sys.exit(1)
"""

    @staticmethod
    def render_script(
            safe_token_id: str,
            code: str,
            step_index: int,
    ) -> str:
        return f"""
import sys
import json
from pathlib import Path
from typing import Dict

{code}

def _load_response() -> Dict:
    response_file: Path = Path(__file__).resolve().parent.parent / "real_responses" / "res_{step_index:04d}.json"
    return json.loads(response_file.read_text(encoding="utf-8"))

if __name__ == "__main__":
    try:
        response = _load_response()
        result = extract_{safe_token_id}(response)
        print(result)
    except Exception:
        sys.exit(1)
"""
