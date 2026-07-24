from typing import Dict, List, Optional, Union

from har_reproducer.models import Extractor, StepRequest, TokenLocation, TokenTrace
from har_reproducer.session import SessionStore


class CurlGenerator:

    def generate(
            self,
            step_index: int,
            request: StepRequest,
            session_store: Optional[SessionStore] = None,
    ) -> str:
        traces: List[TokenTrace] = self._find_token_traces(request, session_store) if session_store else []

        parts: List[str] = [f"curl -X {request.method}", f"'{request.url}'"]
        parts.extend(self._header_parts(request, traces))
        parts.extend(self._cookie_parts(request, traces))
        parts.extend(self._body_parts(request, traces))

        return " \\\n     ".join(parts)

    def _header_parts(self, request: StepRequest, traces: List[TokenTrace]) -> List[str]:
        parts: List[str] = []
        for header, value in request.headers.items():
            trace: Optional[TokenTrace] = self._get_trace_for_value(header, value, traces)
            if trace is not None:
                parts.append(self._trace_comment(trace))
            parts.append(f"-H '{header}: {value}'")
        return parts

    def _cookie_parts(self, request: StepRequest, traces: List[TokenTrace]) -> List[str]:
        parts: List[str] = []
        for cookie, value in request.cookies.items():
            trace: Optional[TokenTrace] = self._get_trace_for_value(cookie, value, traces)
            if trace is not None:
                parts.append(self._trace_comment(trace))
            parts.append(f"--cookie '{cookie}={value}'")
        return parts

    def _body_parts(self, request: StepRequest, traces: List[TokenTrace]) -> List[str]:
        body: Optional[Union[str, bytes]] = request.body
        if not body:
            return []

        body_str: str = self._decode_body(body)
        body_traces: List[TokenTrace] = [trace for trace in traces if trace.location == TokenLocation.BODY_JSON]

        parts: List[str] = [self._trace_comment(trace) for trace in body_traces]
        parts.append(f"--data-binary '{body_str}'")
        return parts

    @staticmethod
    def _decode_body(body: Union[str, bytes]) -> str:
        return body if isinstance(body, str) else body.decode("utf-8", errors="replace")

    @staticmethod
    def _trace_comment(trace: TokenTrace) -> str:
        return (
            f"# Token {trace.location.value}:{trace.key} (id={trace.token_id[:8]}) "
            f"comes from response of step {trace.origin_step}"
        )

    def _find_token_traces(self, request: StepRequest, session_store: SessionStore) -> List[TokenTrace]:
        tokens: Dict[str, str] = session_store.state.tokens
        registry: Dict[str, Extractor] = session_store.state.registry

        traces: List[TokenTrace] = self._header_and_cookie_traces(request, tokens, registry)
        traces.extend(self._body_traces(request, tokens, registry))
        return traces

    def _header_and_cookie_traces(
            self,
            request: StepRequest,
            tokens: Dict[str, str],
            registry: Dict[str, Extractor],
    ) -> List[TokenTrace]:
        traces: List[TokenTrace] = []
        for key, value in {**request.headers, **request.cookies}.items():
            token_id: Optional[str] = self._find_token_id_by_value(value, tokens)
            if token_id is None:
                continue

            extractor: Optional[Extractor] = registry.get(token_id)
            if extractor is None:
                continue

            location: TokenLocation = TokenLocation.HEADER if key in request.headers else TokenLocation.COOKIE
            traces.append(TokenTrace(
                token_id=token_id,
                value=value,
                origin_step=extractor.origin_step or 0,
                location=location,
                key=key,
            ))
        return traces

    def _body_traces(
            self,
            request: StepRequest,
            tokens: Dict[str, str],
            registry: Dict[str, Extractor],
    ) -> List[TokenTrace]:
        body: Optional[Union[str, bytes]] = request.body
        if not body:
            return []

        body_str: str = self._decode_body(body)

        traces: List[TokenTrace] = []
        for token_id, value in tokens.items():
            if value not in body_str:
                continue

            extractor: Optional[Extractor] = registry.get(token_id)
            if extractor is None:
                continue

            traces.append(TokenTrace(
                token_id=token_id,
                value=value,
                origin_step=extractor.origin_step or 0,
                location=TokenLocation.BODY_JSON,
                key="body",
            ))
        return traces

    @staticmethod
    def _find_token_id_by_value(value: str, tokens: Dict[str, str]) -> Optional[str]:
        return next((tid for tid, val in tokens.items() if val == value), None)

    @staticmethod
    def _get_trace_for_value(key: str, value: str, traces: List[TokenTrace]) -> Optional[TokenTrace]:
        return next((trace for trace in traces if trace.key == key and trace.value == value), None)
