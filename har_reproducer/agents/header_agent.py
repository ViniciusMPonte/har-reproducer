from typing import Optional

from .base import BaseAgent


class HeaderAgent(BaseAgent):
    """
    Agent specialized in extracting tokens from HTTP headers.
    """

    def generate_code(self, last_error: Optional[str] = None) -> str:
        return f"""
def extract_{self.safe_token_id}(response: dict) -> str:
    headers = response.get('headers', {{}})
    value = headers.get('{self.token_id}')
    if not value:
        raise Exception("Token not found in headers")
    return value
"""
