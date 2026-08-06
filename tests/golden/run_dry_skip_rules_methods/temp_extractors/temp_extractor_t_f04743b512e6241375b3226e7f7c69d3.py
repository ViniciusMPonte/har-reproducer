
import sys
import json
from typing import Dict
class ExtractorError(Exception): pass


import re

def extract_t_f04743b512e6241375b3226e7f7c69d3(response: dict) -> str:
    body = response.get('body', '')
    if isinstance(body, bytes):
        body = body.decode('utf-8', errors='replace')
    match = re.search('nonce[\'\\"]?\\s*[:=]\\s*[\'\\"]?([\\w\\-.]+)', body, re.DOTALL)
    if not match:
        raise Exception("Token not found via regex")
    return match.group(1)


if __name__ == "__main__":
    response = {'status_code': 200, 'headers': {'Content-Type': 'text/html', 'Set-Cookie': 'SESSIONID=abc123sess; Path=/'}, 'cookies': {'SESSIONID': 'abc123sess'}, 'body': '<html><body><div id="marker">tok_CSS_1</div><script>var nonce = "scr_NONCE_2";</script></body></html>', 'body_mime': 'text/html', 'redirect_url': None, 'skipped': False, 'skip_reason': None}
    try:
        result = extract_t_f04743b512e6241375b3226e7f7c69d3(response)
        print(result)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
