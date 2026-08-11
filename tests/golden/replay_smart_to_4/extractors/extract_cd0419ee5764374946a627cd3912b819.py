
import os
import sys
import json
from pathlib import Path
from typing import Dict


def extract_t_cd0419ee5764374946a627cd3912b819(response: dict) -> str:
    cookies = response.get('cookies', {})
    value = cookies.get('PREFS')
    if not value:
        raise Exception("Token not found in cookies")
    return value


def _load_response() -> Dict:
    override_dir = os.environ.get("HAR_REPRODUCER_RESPONSE_OVERRIDE_DIR")
    if override_dir:
        response_file: Path = Path(override_dir) / "res_0007.json"
    else:
        response_file: Path = Path(__file__).resolve().parent.parent / "real_responses" / "res_0007.json"
    return json.loads(response_file.read_text(encoding="utf-8"))

if __name__ == "__main__":
    try:
        response = _load_response()
        result = extract_t_cd0419ee5764374946a627cd3912b819(response)
        print(result)
    except Exception:
        sys.exit(1)
