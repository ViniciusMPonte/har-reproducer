import re
from re import Match, Pattern
from typing import ClassVar

from har_reproducer.models import SessionState


class SessionStore:
    TOKEN_PLACEHOLDER_PATTERN: ClassVar[Pattern[str]] = re.compile(r"\{\{extractor:([a-f0-9]+)\}\}")

    def __init__(self) -> None:
        self.state: SessionState = SessionState()

    def set_token(self, token_id: str, value: str) -> None:

        self.state.tokens[token_id] = value

    def render(self, template: str) -> str:

        return self.TOKEN_PLACEHOLDER_PATTERN.sub(self._resolve_token_placeholder, template)

    def _resolve_token_placeholder(self, match: Match[str]) -> str:

        token_id: str = match.group(1)
        if token_id not in self.state.tokens:
            return match.group(0)
        return self.state.tokens[token_id]
