import re
from typing import List, Optional

from .base import BaseAgent, Strategy


class RegexAgent(BaseAgent):

    def deterministic_strategies(self) -> List[Strategy]:
        strategies: List[Strategy] = []
        key_pattern: Optional[str] = self._key_pattern()
        if key_pattern is not None:
            strategies.append(self._make_strategy(key_pattern))
        context_pattern: Optional[str] = self._context_pattern()
        if context_pattern is not None:
            strategies.append(self._make_strategy(context_pattern))
        return strategies

    def _key_pattern(self) -> Optional[str]:
        key: Optional[str] = self.key
        if not key or key == "body":
            return None
        return rf"{re.escape(key)}['\"]?\s*[:=]\s*['\"]?({self._value_char_class()})"

    def _context_pattern(self) -> Optional[str]:
        body: Optional[str] = self.response_sample.get("body")
        if not isinstance(body, str):
            return None
        pos: int = body.find(self.expected_value)
        if pos == -1:
            return None
        prefix: str = body[max(0, pos - 20):pos]
        if not prefix.strip():
            return None
        return rf"{re.escape(prefix)}({self._value_char_class()})"

    def _value_char_class(self) -> str:

        if re.fullmatch(r"[\w\-.]+", self.expected_value):
            return r"[\w\-.]+"
        return r".+?"

    def _make_strategy(self, pattern: str) -> Strategy:
        def strategy(last_error: Optional[str] = None) -> Optional[str]:
            return self._build_code(pattern)

        return strategy

    def _build_code(self, pattern: str) -> str:
        return f"""
import re

def extract_{self.safe_token_id}(response: dict) -> str:
    body = response.get('body', '')
    if isinstance(body, bytes):
        body = body.decode('utf-8', errors='replace')
    match = re.search({pattern!r}, body, re.DOTALL)
    if not match:
        raise Exception("Token not found via regex")
    return match.group(1)
"""
