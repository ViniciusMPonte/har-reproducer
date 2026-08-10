
import sys
import json
from typing import Dict
class ExtractorError(Exception): pass


def extract_t_b3defec11e606afd97c5430602861f32(response: dict) -> str:
    cookies = response.get('cookies', {})
    value = cookies.get('SESSIONID')
    if not value:
        raise Exception("Token not found in cookies")
    return value


if __name__ == "__main__":
    response = {'status_code': 200, 'headers': {'Content-Type': 'text/html', 'Set-Cookie': 'SESSIONID=abc123sess; Path=/'}, 'cookies': {'SESSIONID': 'abc123sess'}, 'body': '<html><body><div id="marker">tok_CSS_1</div><script>var nonce = "scr_NONCE_2";</script></body></html>', 'body_mime': 'text/html', 'redirect_url': None, 'skipped': False, 'skip_reason': None}
    try:
        result = extract_t_b3defec11e606afd97c5430602861f32(response)
        print(result)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
