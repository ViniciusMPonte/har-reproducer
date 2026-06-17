from typing import Dict, Optional, List, Any
from src.models.request_record import RecordedRequest, TokenTrace

class CurlGenerator:
    """
    Service responsible for converting an HTTP request into a valid curl command
    with traceability comments for dynamic tokens.
    """
    def generate(self, request: RecordedRequest, session_store: Any = None) -> str:
        """
        Converts a RecordedRequest into a curl command string.
        If session_store is provided, adds traceability comments for dynamic tokens.
        """
        # 1. Identify dynamic tokens used in the request
        traces = []
        if session_store:
            traces = self._find_token_traces(request, session_store)

        # 2. Build the curl command
        parts = [f"curl -X {request.method}"]
        parts.append(f"'{request.url}'")
        
        # Headers with traces
        for header, value in request.headers.items():
            trace = self._get_trace_for_value(header, value, traces)
            line = f"-H '{header}: {value}'"
            if trace:
                parts.append(f"# Token {trace.token_id} comes from response of step {trace.origin_step}")
            parts.append(line)
            
        # Cookies with traces
        for cookie, value in request.cookies.items():
            trace = self._get_trace_for_value(cookie, value, traces)
            line = f"--cookie '{cookie}={value}'"
            if trace:
                parts.append(f"# Token {trace.token_id} comes from response of step {trace.origin_step}")
            parts.append(line)
            
        # Body with traces
        if request.body:
            # For the body, we add traces as a block before the data
            body_traces = [t for t in traces if t.location == "Body"]
            for trace in body_traces:
                parts.append(f"# Token {trace.token_id} comes from response of step {trace.origin_step}")
            parts.append(f"--data-binary '{request.body}'")
            
        return " \\\n     ".join(parts)

    def _find_token_traces(self, request: RecordedRequest, session_store: Any) -> List[TokenTrace]:
        """
        Analyzes the request to find values that match tokens in the session store.
        """
        traces = []
        tokens = session_store.state.tokens
        registry = session_store.state.registry
        
        # Check headers
        for k, v in request.headers.items():
            token_id = self._find_token_id_by_value(v, tokens)
            if token_id:
                extractor = registry.get(token_id)
                if extractor:
                    traces.append(TokenTrace(
                        token_id=token_id,
                        value=v,
                        origin_step=extractor.origin_step or 0,
                        location="Header",
                        key=k
                    ))
                    
        # Check cookies
        for k, v in request.cookies.items():
            token_id = self._find_token_id_by_value(v, tokens)
            if token_id:
                extractor = registry.get(token_id)
                if extractor:
                    traces.append(TokenTrace(
                        token_id=token_id,
                        value=v,
                        origin_step=extractor.origin_step or 0,
                        location="Cookie",
                        key=k
                    ))
        
        # Check body
        if request.body:
            for token_id, value in tokens.items():
                if value in request.body:
                    extractor = registry.get(token_id)
                    if extractor:
                        traces.append(TokenTrace(
                            token_id=token_id,
                            value=value,
                            origin_step=extractor.origin_step or 0,
                            location="Body",
                            key="body"
                        ))
                        
        return traces

    def _find_token_id_by_value(self, value: str, tokens: Dict[str, str]) -> Optional[str]:
        """
        Finds the token_id associated with a given value.
        """
        for tid, val in tokens.items():
            if val == value:
                return tid
        return None

    def _get_trace_for_value(self, key: str, value: str, traces: List[TokenTrace]) -> Optional[TokenTrace]:
        """
        Retrieves the trace for a specific key/value pair.
        """
        for t in traces:
            if t.key == key and t.value == value:
                return t
        return None

