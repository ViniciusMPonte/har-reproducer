import pytest
from har_reproducer.agents.header_agent import HeaderAgent

def test_header_agent_success():
    # The agent expects a response dict with 'headers' key
    response_sample = {"headers": {"X-Auth-Token": "def-456"}}
    agent = HeaderAgent("X-Auth-Token", response_sample, "def-456")
    extractor = agent.run_tdd_loop()
    
    assert extractor is not None
    assert extractor.verified is True
    assert extractor.agent_type == "HeaderAgent"

def test_header_agent_failure():
    response_sample = {"headers": {"Other": "val"}}
    agent = HeaderAgent("X-Auth-Token", response_sample, "def-456")
    extractor = agent.run_tdd_loop(max_attempts=1)
    
    assert extractor is None
