from .base import BaseAgent

class HeaderAgent(BaseAgent):
    """
    Agent specialized in extracting tokens from HTTP headers.
    """
    def generate_code(self) -> str:
        return f"""
def extract_{self.safe_token_id}(response: dict) -> str:
    headers = response.get('headers', {{}})
    value = headers.get('{self.token_id}')
    if not value:
        raise Exception("Token not found in headers")
    return value
"""
