import pytest
from har_reproducer.agents.jsonpath_agent import JSONPathAgent

def test_jsonpath_agent_success():
    response_sample = {"body": '{"session_id": "jwt-789"}'}
    agent = JSONPathAgent("session_id", response_sample, "jwt-789")
    extractor = agent.run_tdd_loop()
    
    assert extractor is not None
    assert extractor.verified is True
    assert extractor.agent_type == "JSONPathAgent"

def test_jsonpath_agent_failure():
    response_sample = {"body": '{"other": "val"}'}
    agent = JSONPathAgent("session_id", response_sample, "jwt-789")
    extractor = agent.run_tdd_loop(max_attempts=1)
    
    assert extractor is None
