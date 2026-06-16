from .base import BaseAgent
import re

class RegexAgent(BaseAgent):
    """
    Agent specialized in extracting tokens using Regular Expressions.
    """
    def generate_code(self) -> str:
        return f"""
import re

def extract_{self.safe_token_id}(response: dict) -> str:
    body = response.get('body', '')
    match = re.search(r'{self.token_id}=([\\w-]+)', body)
    if not match:
        raise Exception("Token not found via regex")
    return match.group(1)
"""
