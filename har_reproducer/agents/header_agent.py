from typing import List, Optional

from .base import BaseAgent, Strategy


class HeaderAgent(BaseAgent):

    def deterministic_strategies(self) -> List[Strategy]:
        return [self._by_name]

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
