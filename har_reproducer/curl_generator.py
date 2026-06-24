from typing import Dict, Optional, List, Any

from .models import StepRequest, TokenTrace


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
        traces = self._find_token_traces(request, session_store) if session_store else []

        parts = [f"curl -X {request.method}", f"'{request.url}'"]

        # Headers
        for header, value in request.headers.items():
            if trace := self._get_trace_for_value(header, value, traces):
                parts.append(f"# Token {trace.token_id} comes from response of step {trace.origin_step}")
            parts.append(f"-H '{header}: {value}'")

        # Cookies
        for cookie, value in request.cookies.items():
            if trace := self._get_trace_for_value(cookie, value, traces):
                parts.append(f"# Token {trace.token_id} comes from response of step {trace.origin_step}")
            parts.append(f"--cookie '{cookie}={value}'")

        # Body
        if request.body:
            body_traces = [t for t in traces if t.location == "Body"]
            for trace in body_traces:
                parts.append(f"# Token {trace.token_id} comes from response of step {trace.origin_step}")
            parts.append(f"--data-binary '{request.body}'")

        return " \\\n     ".join(parts)

    def _find_token_traces(self, request: StepRequest, session_store: Any) -> List[TokenTrace]:
        traces = []
        tokens = session_store.state.tokens
        registry = session_store.state.registry

        # Check headers and cookies
        for key, value in {**request.headers, **request.cookies}.items():
            if tid := self._find_token_id_by_value(value, tokens):
                if ext := registry.get(tid):
                    location = "Header" if key in request.headers else "Cookie"
                    traces.append(TokenTrace(
                        token_id=tid, value=value, origin_step=ext.origin_step or 0,
                        location=location, key=key
                    ))

        # Check body
        if request.body:
            for tid, val in tokens.items():
                if val in request.body:
                    if ext := registry.get(tid):
                        traces.append(TokenTrace(
                            token_id=tid, value=val, origin_step=ext.origin_step or 0,
                            location="Body", key="body"
                        ))
        return traces

    def _find_token_id_by_value(self, value: str, tokens: Dict[str, str]) -> Optional[str]:
        return next((tid for tid, val in tokens.items() if val == value), None)

    def _get_trace_for_value(self, key: str, value: str, traces: List[TokenTrace]) -> Optional[TokenTrace]:
        return next((t for t in traces if t.key == key and t.value == value), None)
