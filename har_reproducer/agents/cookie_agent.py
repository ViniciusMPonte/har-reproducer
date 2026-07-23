from typing import List, Optional

from .base_agent import BaseAgent
from ..contracts import Strategy

class CookieAgent(BaseAgent):

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
