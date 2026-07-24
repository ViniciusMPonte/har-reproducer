from typing import Any, Dict, Optional


class ExtractorPrompt:

    @staticmethod
    def build(
            safe_token_id: str,
            location: Optional[str],
            path: Optional[str],
            expected_value: str,
            response_sample: Dict[str, Any],
            last_error: Optional[str] = None,
    ) -> str:
        error_section: str = (
            f"\nThe previous attempt failed with this error:\n{last_error}\n"
            if last_error
            else ""
        )
        return f"""You are a Python code generator for HTTP token extraction.

Write a single Python function named `extract_{safe_token_id}` that receives
one argument `response` (a dict with keys like 'headers', 'cookies', 'body') and
returns the extracted token value as a string. Raise an Exception if the token is
not found. Return ONLY the function code inside a ```python code block, with any
required imports inside or above the function.

Token location: {location}
Original key/path: {path}
Expected returned value: {expected_value!r}
Response sample: {response_sample!r}
{error_section}"""
