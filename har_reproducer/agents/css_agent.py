from .base import BaseAgent

class CSSAgent(BaseAgent):
    """
    Agent specialized in extracting tokens from HTML bodies using CSS selectors.
    """
    def generate_code(self) -> str:
        return f"""
from bs4 import BeautifulSoup

def extract_{self.safe_token_id}(response: dict) -> str:
    body = response.get('body', '')
    soup = BeautifulSoup(body, 'html.parser')
    element = soup.select_one('.{self.token_id}')
    if not element:
        raise Exception("Token element not found in HTML")
    return element.text.strip()
"""
