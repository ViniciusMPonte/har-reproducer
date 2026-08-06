
import sys
import json
from typing import Dict
class ExtractorError(Exception): pass


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


if __name__ == "__main__":
    response = {'status_code': 200, 'headers': {'Content-Type': 'application/json'}, 'cookies': {}, 'body': '{"id": 4242, "ok": true}', 'body_mime': 'application/json', 'redirect_url': None, 'skipped': False, 'skip_reason': None}
    try:
        result = extract_t_3a2dd5b363bd0701c13a2da19b03abc9(response)
        print(result)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
