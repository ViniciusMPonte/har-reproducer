import re
from typing import Dict, List, Optional

from har_reproducer.agents.base_agent import BaseAgent
from har_reproducer.contracts import Strategy


class HeaderAgent(BaseAgent):

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
    headers = response.get('headers', {{}})
    target = {key!r}
    value = headers.get(target)
    if value is None:
        lowered = {{str(k).lower(): v for k, v in headers.items()}}
        value = lowered.get(target.lower())
    if not value:
        raise Exception("Token not found in headers")
    return value
"""

    def _header_value(self) -> Optional[str]:
        key: Optional[str] = self.key
        if not key:
            return None
        headers: Dict[str, str] = self.response_sample.get("headers", {})
        value: Optional[str] = headers.get(key)
        if value is None:
            lowered: Dict[str, str] = {str(k).lower(): v for k, v in headers.items()}
            value = lowered.get(key.lower())
        return value

    def _context_pattern(self) -> Optional[str]:
        header_value: Optional[str] = self._header_value()
        if not header_value:
            return None
        pos: int = header_value.find(self.expected_value)
        if pos == -1:
            return None
        prefix: str = header_value[:pos]
        suffix: str = header_value[pos + len(self.expected_value):]
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
    headers = response.get('headers', {{}})
    target = {key!r}
    value = headers.get(target)
    if value is None:
        lowered = {{str(k).lower(): v for k, v in headers.items()}}
        value = lowered.get(target.lower())
    if not value:
        raise Exception("Token not found in headers")
    match = re.search({pattern!r}, value)
    if not match:
        raise Exception("Token not found via substring match in header")
    return match.group(1)
"""
