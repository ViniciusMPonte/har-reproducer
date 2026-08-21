
import os
import sys
import json
from pathlib import Path
from typing import Dict


import json

def extract_t_cd1ab83b0d6eaa4602386d811ffa16bb(response: dict) -> str:
    body_text = response.get('body', '')
    data = json.loads(body_text) if isinstance(body_text, str) else body_text
    try:
        value = data['token']
    except (KeyError, IndexError, TypeError) as e:
        raise Exception(f"Token not found in JSON body: {e}")
    if value is None:
        raise Exception("Token not found in JSON body")
    return str(value)


def _load_response() -> Dict:
    override_dir = os.environ.get("HAR_REPRODUCER_RESPONSE_OVERRIDE_DIR")
    if override_dir:
        response_file: Path = Path(override_dir) / "res_0000.json"
    else:
        response_file: Path = Path(__file__).resolve().parent.parent / "real_responses" / "res_0000.json"
    return json.loads(response_file.read_text(encoding="utf-8"))

if __name__ == "__main__":
    try:
        response = _load_response()
        result = extract_t_cd1ab83b0d6eaa4602386d811ffa16bb(response)
        print(result)
    except Exception:
        sys.exit(1)
