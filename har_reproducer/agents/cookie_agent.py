import re
from typing import List, Optional

from har_reproducer.agents.base_agent import BaseAgent
from har_reproducer.contracts import Strategy


class CookieAgent(BaseAgent):

    def deterministic_strategies(self) -> List[Strategy]:
        strategies: List[Strategy] = [self._by_name]
        context_pattern: Optional[str] = self._context_pattern()
        if context_pattern is not None:
            strategies.append(self._make_context_strategy(context_pattern))
        return strategies

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

    def _context_pattern(self) -> Optional[str]:
        key: Optional[str] = self.key
        if not key:
            return None
        cookie_value: Optional[str] = self.response_sample.get("cookies", {}).get(key)
        if not cookie_value:
            return None
        pos: int = cookie_value.find(self.expected_value)
        if pos == -1:
            return None
        prefix: str = cookie_value[:pos]
        suffix: str = cookie_value[pos + len(self.expected_value):]
        boundary: str = rf"(?={re.escape(suffix[0])})" if suffix else "$"
        return rf"{re.escape(prefix)}({self.lazy_value_char_class()}){boundary}"

    def _make_context_strategy(self, pattern: str) -> Strategy:
        def strategy(last_error: Optional[str] = None) -> Optional[str]:
            return self._build_context_code(pattern)
        return strategy

    def _build_context_code(self, pattern: str) -> str:
        key: Optional[str] = self.key
        return f"""
import re

def extract_{self.safe_token_id}(response: dict) -> str:
    cookies = response.get('cookies', {{}})
    value = cookies.get({key!r})
    if not value:
        raise Exception("Token not found in cookies")
    match = re.search({pattern!r}, value)
    if not match:
        raise Exception("Token not found via substring match in cookie")
    return match.group(1)
"""
