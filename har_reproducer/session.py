from typing import Any, Dict, List, Union

from .models import SessionState


class SessionStore:

    def __init__(self) -> None:
        self.state: SessionState = SessionState()

    def set_token(self, token_id: str, value: str) -> None:

        self.state.tokens[token_id] = value

    def get_token(self, token_id: str) -> str:

        return self.state.tokens[token_id]

    def render(self, template: str) -> str:

        result: str = template
        for token_id, value in self.state.tokens.items():
            result = result.replace(f"{{{{{token_id}}}}}", value)
        return result

    def render_dict(self, data: Union[Dict[str, Any], List[Any], str, Any]) -> Any:

        if isinstance(data, dict):
            return {k: self.render_dict(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self.render_dict(i) for i in data]
        elif isinstance(data, str):
            return self.render(data)
        return data
