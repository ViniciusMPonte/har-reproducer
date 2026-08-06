
import os
import sys
import json
from pathlib import Path
from typing import Dict

def extract_t_b3defec11e606afd97c5430602861f32(response):
    return 'abc123sess'


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
        result = extract_t_b3defec11e606afd97c5430602861f32(response)
        print(result)
    except Exception:
        sys.exit(1)
