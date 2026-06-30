from typing import Any, Dict, List, Union

from .models import SessionState


class SessionStore:
    """
    Manages the global state of a reproduction session, providing
    mechanisms to store, retrieve, and interpolate dynamic tokens.
    """

    def __init__(self) -> None:
        self.state: SessionState = SessionState()

    def set_token(self, token_id: str, value: str) -> None:
        """Updates a token value in the session state."""
        self.state.tokens[token_id] = value

    def get_token(self, token_id: str) -> str:
        """Retrieves a token value. Raises KeyError if not found."""
        return self.state.tokens[token_id]

    def render(self, template: str) -> str:
        """
        Interpolates tokens into a template string.
        Tokens are expected to be in the format {{token_id}}.
        """
        result: str = template
        for token_id, value in self.state.tokens.items():
            result = result.replace(f"{{{{{token_id}}}}}", value)
        return result

    def render_dict(self, data: Union[Dict[str, Any], List[Any], str, Any]) -> Any:
        """
        Recursively interpolates tokens within a dictionary.
        """
        if isinstance(data, dict):
            return {k: self.render_dict(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self.render_dict(i) for i in data]
        elif isinstance(data, str):
            return self.render(data)
        return data
