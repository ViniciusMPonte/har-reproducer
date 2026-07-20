from typing import List, Optional

from .base import BaseAgent, Strategy


class CookieAgent(BaseAgent):
    """
    Agent specialized in extracting tokens from HTTP cookies.

    Cookies are keyed directly by name, so a single deterministic strategy using
    the real cookie name (``self.key``) is enough; the LLM fallback only kicks in
    when the name is unknown or the sample does not match.
    """

    def deterministic_strategies(self) -> List[Strategy]:
        return [self._by_name]

    def _by_name(self, last_error: Optional[str] = None) -> Optional[str]:
        key: Optional[str] = self.key
        if not key:
            return None
        return f"""
def extract_{self.safe_token_id}(response: dict) -> str:
    cookies = response.get('cookies', {{}})
    value = cookies.get({key!r})
    if not value:
        raise Exception("Token not found in cookies")
    return value
"""
