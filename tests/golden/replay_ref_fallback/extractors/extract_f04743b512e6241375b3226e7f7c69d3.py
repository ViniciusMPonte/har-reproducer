
import os
import sys
import json
from pathlib import Path
from typing import Dict


import re

def extract_t_f04743b512e6241375b3226e7f7c69d3(response: dict) -> str:
    body = response.get('body', '')
    if isinstance(body, bytes):
        body = body.decode('utf-8', errors='replace')
    match = re.search('nonce[\'\\"]?\\s*[:=]\\s*[\'\\"]?([\\w\\-.]+)', body, re.DOTALL)
    if not match:
        raise Exception("Token not found via regex")
    return match.group(1)


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
        result = extract_t_f04743b512e6241375b3226e7f7c69d3(response)
        print(result)
    except Exception:
        sys.exit(1)
