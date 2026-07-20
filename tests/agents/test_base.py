import pytest
from har_reproducer.agents.base import BaseAgent

class MockAgent(BaseAgent):
    def generate_code(self, last_error=None) -> str:
        return f"def extract_{self.safe_token_id}(response: dict) -> str: return response['body']"
    
    @property
    def __class__(self):
        class MockCookieAgent(BaseAgent): pass
        MockCookieAgent.__name__ = "CookieAgent"
        return MockCookieAgent

def test_base_agent_tdd_success():
    agent = MockAgent("test_token", {"body": "value123"}, "value123")
    extractor = agent.run_tdd_loop()
    
    assert extractor is not None
    assert extractor.token_id == "test_token"
    assert extractor.verified is True
    assert "def extract_test_token" in extractor.code

def test_base_agent_tdd_failure():
    class FailingAgent(BaseAgent):
        def generate_code(self, last_error=None) -> str:
            return f"def extract_{self.safe_token_id}(response: dict) -> str: return 'wrong'"
            
    agent = FailingAgent("test_token", {"body": "value123"}, "value123")
    extractor = agent.run_tdd_loop(max_attempts=2)
    
    assert extractor is None

def test_base_agent_path_key_property():
    agent = BaseAgent("hash123", {}, "v", path="cookie:session_id")
    assert agent.key == "session_id"
    # token_id must never be used as the key
    assert agent.token_id == "hash123"
