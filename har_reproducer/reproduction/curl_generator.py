import shlex
from typing import List, Optional, Tuple, Union

from har_reproducer.models import AgentType, DynamicToken, Extractor, StepRequest
from har_reproducer.replay.curl_token_comment import CurlTokenComment, OriginStatusPhrase
from har_reproducer.session import SessionStore


class CurlGenerator:

    def __init__(self, curl_token_comment: CurlTokenComment, session_store: SessionStore) -> None:
        self.curl_token_comment: CurlTokenComment = curl_token_comment
        self.session_store: SessionStore = session_store

    def generate(self, request: StepRequest, tokens: List[DynamicToken]) -> str:
        comment_lines: List[str] = self._token_comments(tokens)
        curl_block: str = " \\\n     ".join(self._curl_parts(request))

        if not comment_lines:
            return curl_block
        return "\n".join(comment_lines) + "\n" + curl_block

    def _curl_parts(self, request: StepRequest) -> List[str]:
        parts: List[str] = [self._request_line(request), shlex.quote(request.url)]
        parts.extend(self._header_parts(request))

        cookie_part: Optional[str] = self._cookie_part(request)
        if cookie_part is not None:
            parts.append(cookie_part)

        parts.extend(self._body_part(request))
        return parts

    @staticmethod
    def _request_line(request: StepRequest) -> str:
        return f"curl -X {request.method}"

    @staticmethod
    def _header_parts(request: StepRequest) -> List[str]:
        parts: List[str] = []
        for key, value in request.headers.items():
            if key.lower() == "cookie" and request.cookies:
                continue
            quoted_header: str = shlex.quote(f"{key}: {value}")
            parts.append(f"-H {quoted_header}")
        return parts

    @staticmethod
    def _cookie_part(request: StepRequest) -> Optional[str]:
        if not request.cookies:
            return None

        combined_cookies: str = "; ".join(f"{key}={value}" for key, value in request.cookies.items())
        quoted_cookies: str = shlex.quote(combined_cookies)
        return f"--cookie {quoted_cookies}"

    def _body_part(self, request: StepRequest) -> List[str]:
        body: Optional[Union[str, bytes]] = request.body
        if not body:
            return []

        quoted_body: str = shlex.quote(self._decode_body(body))
        return [f"--data-binary {quoted_body}"]

    def _token_comments(self, tokens: List[DynamicToken]) -> List[str]:
        lines: List[str] = [
            self.curl_token_comment.format_dependency_line(
                token.token_id, token.origin_step, self._origin_status(token)
            )
            for token in tokens if token.status == "Resolved"
        ]

        static: List[Tuple[str, int]] = [
            (token.path, token.origin_step) for token in tokens
            if token.status == "Static" and token.origin_step is not None
        ]
        if static:
            lines.append(self.curl_token_comment.format_static_line(static))

        unresolved: List[str] = [token.path for token in tokens if token.origin_step is None]
        if unresolved:
            lines.append(self.curl_token_comment.format_unresolved_line(unresolved))
        return lines

    def _origin_status(self, token: DynamicToken) -> Optional[OriginStatusPhrase]:
        extractor: Optional[Extractor] = self.session_store.state.registry.get(token.token_id)
        assert extractor is not None
        if extractor.agent_type == AgentType.LITERAL:
            return OriginStatusPhrase.UNDETERMINED
        if extractor.agent_type == AgentType.LITERAL_FALLBACK:
            return OriginStatusPhrase.EXTRACTION_EXHAUSTED
        return None

    @staticmethod
    def _decode_body(body: Union[str, bytes]) -> str:
        return body if isinstance(body, str) else body.decode("utf-8", errors="replace")
