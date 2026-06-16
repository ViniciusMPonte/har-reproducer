import pytest
from har_reproducer.agents.regex_agent import RegexAgent

def test_regex_agent_success():
    response_sample = {"body": "some content token_val=ghi-789 more content"}
    agent = RegexAgent("token_val", response_sample, "ghi-789")
    extractor = agent.run_tdd_loop()
    
    assert extractor is not None
    assert extractor.verified is True
    assert extractor.agent_type == "RegexAgent"

def test_regex_agent_failure():
    response_sample = {"body": "some content without token"}
    agent = RegexAgent("token_val", response_sample, "ghi-789")
    extractor = agent.run_tdd_loop(max_attempts=1)
    
    assert extractor is None
