import json
from typing import Any, List, Optional, Tuple

from .base import BaseAgent, Strategy

AccessPath = List[Tuple[str, Any]]


class JSONPathAgent(BaseAgent):

    def deterministic_strategies(self) -> List[Strategy]:
        paths: List[AccessPath] = self._find_value_paths()
        return [self._make_strategy(path) for path in paths]

    def _find_value_paths(self) -> List[AccessPath]:
        body: Any = self.response_sample.get("body", "")
        try:
            data: Any = json.loads(body) if isinstance(body, str) else body
        except (json.JSONDecodeError, TypeError):
            return []

        matches: List[AccessPath] = []
        self._walk(data, [], matches)

        matches.sort(key=len)
        return matches

    def _walk(self, node: Any, current: AccessPath, matches: List[AccessPath]) -> None:
        if self._matches_value(node):
            matches.append(list(current))
            return
        if isinstance(node, dict):
            for k, v in node.items():
                self._walk(v, current + [("key", k)], matches)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                self._walk(v, current + [("index", i)], matches)

    def _matches_value(self, node: Any) -> bool:
        if isinstance(node, (dict, list)):
            return False
        return str(node) == self.expected_value

    def _make_strategy(self, path: AccessPath) -> Strategy:
        def strategy(last_error: Optional[str] = None) -> Optional[str]:
            return self._build_code(path)

        return strategy

    def _build_code(self, path: AccessPath) -> str:
        accessor: str = "".join(f"[{key!r}]" for _, key in path)
        return f"""
import json

def extract_{self.safe_token_id}(response: dict) -> str:
    body_text = response.get('body', '')
    data = json.loads(body_text) if isinstance(body_text, str) else body_text
    try:
        value = data{accessor}
    except (KeyError, IndexError, TypeError) as e:
        raise Exception(f"Token not found in JSON body: {{e}}")
    if value is None:
        raise Exception("Token not found in JSON body")
    return str(value)
"""
