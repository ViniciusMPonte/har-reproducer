
import os
import sys
import json
from pathlib import Path
from typing import Dict


def extract_t_3a2dd5b363bd0701c13a2da19b03abc9(response: dict) -> str:
    headers = response.get('headers', {})
    target = 'Content-Type'
    value = headers.get(target)
    if value is None:
        lowered = {str(k).lower(): v for k, v in headers.items()}
        value = lowered.get(target.lower())
    if not value:
        raise Exception("Token not found in headers")
    return value


def _load_response() -> Dict:
    override_dir = os.environ.get("HAR_REPRODUCER_RESPONSE_OVERRIDE_DIR")
    if override_dir:
        response_file: Path = Path(override_dir) / "res_0003.json"
    else:
        response_file: Path = Path(__file__).resolve().parent.parent / "real_responses" / "res_0003.json"
    return json.loads(response_file.read_text(encoding="utf-8"))

if __name__ == "__main__":
    try:
        response = _load_response()
        result = extract_t_3a2dd5b363bd0701c13a2da19b03abc9(response)
        print(result)
    except Exception:
        sys.exit(1)
