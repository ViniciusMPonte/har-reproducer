import json
from typing import Any, List, Optional, Tuple

from .base import BaseAgent, Strategy


class JSONPathAgent(BaseAgent):

    def deterministic_strategies(self) -> List[Strategy]:
        paths: List[List[Tuple[str, Any]]] = self._find_value_paths()
        return [self._make_strategy(path) for path in paths]

    def _find_value_paths(self) -> List[List[Tuple[str, Any]]]:
        body: Any = self.response_sample.get("body", "")
        try:
            data: Any = json.loads(body) if isinstance(body, str) else body
        except (json.JSONDecodeError, TypeError):
            return []

        matches: List[List[Tuple[str, Any]]] = []
        self._walk(data, [], matches)

        matches.sort(key=len)
        return matches

    def _walk(self, node: Any, current: List[Tuple[str, Any]], matches: List[List[Tuple[str, Any]]]) -> None:
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

    def _make_strategy(self, path: List[Tuple[str, Any]]) -> Strategy:
        def strategy(last_error: Optional[str] = None) -> Optional[str]:
            return self._build_code(path)

        return strategy

    def _build_code(self, path: List[Tuple[str, Any]]) -> str:
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
