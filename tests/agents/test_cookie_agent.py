import pytest
from har_reproducer.agents.cookie_agent import CookieAgent

def test_cookie_agent_success():
    response_sample = {"cookies": {"session_id": "abc-123"}}
    agent = CookieAgent("tok_hash", response_sample, "abc-123", path="cookie:session_id")
    extractor = agent.run_tdd_loop()
    
    assert extractor is not None
    assert extractor.verified is True
    assert extractor.agent_type == "CookieAgent"

def test_cookie_agent_failure():
    response_sample = {"cookies": {"other": "val"}}
    agent = CookieAgent("tok_hash", response_sample, "abc-123", path="cookie:session_id")
    extractor = agent.run_tdd_loop(max_attempts=1)
    
    assert extractor is None
