from .base import BaseAgent

class CookieAgent(BaseAgent):
    """
    Agent specialized in extracting tokens from HTTP cookies.
    """
    def generate_code(self) -> str:
        return f"""
def extract_{self.safe_token_id}(response: dict) -> str:
    cookies = response.get('cookies', {{}})
    value = cookies.get('{self.token_id}')
    if not value:
        raise Exception("Token not found in cookies")
    return value
"""
