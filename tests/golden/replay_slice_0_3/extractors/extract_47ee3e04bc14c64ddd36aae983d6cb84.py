
import os
import sys
import json
from pathlib import Path
from typing import Dict


from bs4 import BeautifulSoup

def extract_t_47ee3e04bc14c64ddd36aae983d6cb84(response: dict) -> str:
    body = response.get('body', '')
    soup = BeautifulSoup(body, 'html.parser')
    element = soup.select_one('#marker')
    if not element:
        raise Exception("Token element not found in HTML")
    value = element.get_text(strip=True)
    if not value:
        raise Exception("Token value not found in HTML element")
    return value


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
        result = extract_t_47ee3e04bc14c64ddd36aae983d6cb84(response)
        print(result)
    except Exception:
        sys.exit(1)
