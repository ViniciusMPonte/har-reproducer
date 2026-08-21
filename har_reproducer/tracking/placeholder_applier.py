from typing import List, Optional, Union

from har_reproducer.models import DynamicToken, Extractor, StepRequest, TokenLocation
from har_reproducer.session import SessionStore


class PlaceholderApplier:

    def __init__(self, session_store: SessionStore) -> None:
        self.session_store: SessionStore = session_store

    def apply(self, request: StepRequest, tokens: List[DynamicToken]) -> None:
        for token in self._ordered_by_value_length(tokens):
            self._apply_token(request, token)

    @staticmethod
    def _ordered_by_value_length(tokens: List[DynamicToken]) -> List[DynamicToken]:
        return sorted(tokens, key=lambda token: len(token.extracted_value), reverse=True)

    def _apply_token(self, request: StepRequest, token: DynamicToken) -> None:
        if not token.extracted_value:
            return

        extractor: Optional[Extractor] = self._verified_extractor(token.token_id)
        if extractor is None:
            return

        placeholder: str = self._placeholder_for(token.token_id)
        self._replace_in_url(request, token.extracted_value, placeholder)
        self._replace_in_headers(request, token.extracted_value, placeholder)
        self._replace_in_cookies(request, token.extracted_value, placeholder)
        self._replace_in_body(request, token.extracted_value, placeholder)

    def _verified_extractor(self, token_id: str) -> Optional[Extractor]:
        extractor: Optional[Extractor] = self.session_store.state.registry.get(token_id)
        if extractor is None or not extractor.verified:
            return None
        return extractor

    @staticmethod
    def _placeholder_for(token_id: str) -> str:
        return f"{{{{extractor:{token_id}}}}}"

    @staticmethod
    def _replace_in_url(request: StepRequest, value: str, placeholder: str) -> None:
        request.url = request.url.replace(value, placeholder)

    @staticmethod
    def _replace_in_headers(request: StepRequest, value: str, placeholder: str) -> None:
        for key, header_value in list(request.headers.items()):
            if value in header_value:
                request.headers[key] = header_value.replace(value, placeholder)

    @staticmethod
    def _replace_in_cookies(request: StepRequest, value: str, placeholder: str) -> None:
        for key, cookie_value in list(request.cookies.items()):
            if value in cookie_value:
                request.cookies[key] = cookie_value.replace(value, placeholder)

    @staticmethod
    def _replace_in_body(request: StepRequest, value: str, placeholder: str) -> None:
        body: Optional[Union[str, bytes]] = request.body
        if not body:
            return

        if isinstance(body, bytes):
            request.body = PlaceholderApplier._replace_in_bytes(body, value, placeholder)
        elif value in body:
            request.body = body.replace(value, placeholder)

    @staticmethod
    def _replace_in_bytes(body: bytes, value: str, placeholder: str) -> bytes:
        try:
            body_str: str = body.decode("utf-8")
        except UnicodeDecodeError:
            return body

        if value in body_str:
            return body_str.replace(value, placeholder).encode("utf-8")
        return body
