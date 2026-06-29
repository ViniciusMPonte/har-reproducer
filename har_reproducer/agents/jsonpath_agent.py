from typing import Optional

from .base import BaseAgent


class JSONPathAgent(BaseAgent):
    """
    Agent specialized in extracting tokens from JSON bodies using jsonpath.
    """

    def generate_code(self, last_error: Optional[str] = None) -> str:
        return f"""
import json

def extract_{self.safe_token_id}(response: dict) -> str:
    body_text = response.get('body', '')
    try:
        data = json.loads(body_text)
        value = data.get('{self.token_id}')
        if not value:
            raise Exception("Token not found in JSON body")
        return str(value)
    except Exception as e:
        raise Exception(f"JSON parsing failed: {{e}}")
"""
