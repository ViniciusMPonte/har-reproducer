from typing import Dict, Optional, List
from src.models.request_record import RecordedRequest, TokenTrace

class CurlGenerator:
    """
    Service responsible for converting an HTTP request into a valid curl command
    with traceability comments for dynamic tokens.
    """
    def generate(self, request: RecordedRequest) -> str:
        """
        Converts a RecordedRequest into a curl command string.
        """
        parts = [f"curl -X {request.method}"]
        
        # URL
        parts.append(f"'{request.url}'")
        
        # Headers
        for header, value in request.headers.items():
            parts.append(f"-H '{header}: {value}'")
            
        # Cookies
        for cookie, value in request.cookies.items():
            parts.append(f"--cookie '{cookie}={value}'")
            
        # Body
        if request.body:
            # Use --data-binary to preserve formatting and special characters
            parts.append(f"--data-binary '{request.body}'")
            
        return " \\\n     ".join(parts)
