from typing import Any, Dict


def render_extractor_script(
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
