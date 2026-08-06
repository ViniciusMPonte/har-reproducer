
import sys
import json
from typing import Dict
class ExtractorError(Exception): pass


def extract_t_cd0419ee5764374946a627cd3912b819(response: dict) -> str:
    cookies = response.get('cookies', {})
    value = cookies.get('PREFS')
    if not value:
        raise Exception("Token not found in cookies")
    return value


if __name__ == "__main__":
    response = {'status_code': 200, 'headers': {'Content-Type': 'text/html'}, 'cookies': {'PREFS': 'xyz789'}, 'body': '<html><body>prefs</body></html>', 'body_mime': 'text/html', 'redirect_url': None, 'skipped': False, 'skip_reason': None}
    try:
        result = extract_t_cd0419ee5764374946a627cd3912b819(response)
        print(result)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
