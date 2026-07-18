from typing import Any, Dict, List, Optional

from .models import StepRequest, TokenLocation, TokenTrace


class CurlGenerator:
    """
    Service responsible for converting an HTTP request into a valid curl command
    with traceability comments for dynamic tokens.
    """

    def generate(self, step_index: int, request: StepRequest, session_store: Any = None) -> str:
        """
        Converts a StepRequest into a curl command string.
        If session_store is provided, adds traceability comments for dynamic tokens.
        """
        traces: List[TokenTrace] = self._find_token_traces(request, session_store) if session_store else []

        parts: List[str] = [f"curl -X {request.method}", f"'{request.url}'"]

        # Headers
        for header, value in request.headers.items():
            if trace := self._get_trace_for_value(header, value, traces):
                parts.append(self._trace_comment(trace))
            parts.append(f"-H '{header}: {value}'")

        # Cookies
        for cookie, value in request.cookies.items():
            if trace := self._get_trace_for_value(cookie, value, traces):
                parts.append(self._trace_comment(trace))
            parts.append(f"--cookie '{cookie}={value}'")

        # Body
        if request.body:
            body_str: str = (
                request.body if isinstance(request.body, str)
                else request.body.decode("utf-8", errors="replace")
            )
            body_traces: List[TokenTrace] = [t for t in traces if t.location == TokenLocation.BODY_JSON]
            for trace in body_traces:
                parts.append(self._trace_comment(trace))
            parts.append(f"--data-binary '{body_str}'")

        return " \\\n     ".join(parts)

    def _trace_comment(self, trace: TokenTrace) -> str:
        return (
            f"# Token {trace.location.value}:{trace.key} (id={trace.token_id[:8]}) "
            f"comes from response of step {trace.origin_step}"
        )

    def _find_token_traces(self, request: StepRequest, session_store: Any) -> List[TokenTrace]:
        traces: List[TokenTrace] = []
        tokens: Dict[str, str] = session_store.state.tokens
        registry: Dict[str, Any] = session_store.state.registry

        # Check headers and cookies
        for key, value in {**request.headers, **request.cookies}.items():
            if tid := self._find_token_id_by_value(value, tokens):
                if ext := registry.get(tid):
                    location: TokenLocation = (
                        TokenLocation.HEADER if key in request.headers else TokenLocation.COOKIE
                    )
                    traces.append(TokenTrace(
                        token_id=tid,
                        value=value,
                        origin_step=ext.origin_step or 0,
                        location=location,
                        key=key,
                    ))

        # Check body
        if request.body:
            body_str: str = (
                request.body if isinstance(request.body, str)
                else request.body.decode("utf-8", errors="replace")
            )
            for tid, val in tokens.items():
                if val in body_str:
                    if ext := registry.get(tid):
                        traces.append(TokenTrace(
                            token_id=tid,
                            value=val,
                            origin_step=ext.origin_step or 0,
                            location=TokenLocation.BODY_JSON,
                            key="body",
                        ))
        return traces

    def _find_token_id_by_value(self, value: str, tokens: Dict[str, str]) -> Optional[str]:
        return next((tid for tid, val in tokens.items() if val == value), None)

    def _get_trace_for_value(self, key: str, value: str, traces: List[TokenTrace]) -> Optional[TokenTrace]:
        return next((t for t in traces if t.key == key and t.value == value), None)
