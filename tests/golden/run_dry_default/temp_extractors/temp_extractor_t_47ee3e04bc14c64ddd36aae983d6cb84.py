
import sys
import json
from typing import Dict
class ExtractorError(Exception): pass


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


if __name__ == "__main__":
    response = {'status_code': 200, 'headers': {'Content-Type': 'text/html', 'Set-Cookie': 'SESSIONID=abc123sess; Path=/'}, 'cookies': {'SESSIONID': 'abc123sess'}, 'body': '<html><body><div id="marker">tok_CSS_1</div><script>var nonce = "scr_NONCE_2";</script></body></html>', 'body_mime': 'text/html', 'redirect_url': None, 'skipped': False, 'skip_reason': None}
    try:
        result = extract_t_47ee3e04bc14c64ddd36aae983d6cb84(response)
        print(result)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
