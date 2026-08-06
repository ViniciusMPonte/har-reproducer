
import sys
import json
from typing import Dict
class ExtractorError(Exception): pass


import json

def extract_t_ade6a53080262635799eb7ec66e824e8(response: dict) -> str:
    body_text = response.get('body', '')
    data = json.loads(body_text) if isinstance(body_text, str) else body_text
    try:
        value = data['id']
    except (KeyError, IndexError, TypeError) as e:
        raise Exception(f"Token not found in JSON body: {e}")
    if value is None:
        raise Exception("Token not found in JSON body")
    return str(value)


if __name__ == "__main__":
    response = {'status_code': 200, 'headers': {'Content-Type': 'application/json'}, 'cookies': {}, 'body': '{"id": 4242, "ok": true}', 'body_mime': 'application/json', 'redirect_url': None, 'skipped': False, 'skip_reason': None}
    try:
        result = extract_t_ade6a53080262635799eb7ec66e824e8(response)
        print(result)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
