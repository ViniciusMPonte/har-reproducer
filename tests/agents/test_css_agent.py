import pytest
from har_reproducer.agents.css_agent import CSSAgent

def test_css_agent_success():
    response_sample = {"body": '<html><body><div class="token_val">abc-def</div></body></html>'}
    agent = CSSAgent("token_val", response_sample, "abc-def")
    extractor = agent.run_tdd_loop()
    
    assert extractor is not None
    assert extractor.verified is True
    assert extractor.agent_type == "CSSAgent"

def test_css_agent_failure():
    response_sample = {"body": '<html><body><div>No token here</div></body></html>'}
    agent = CSSAgent("token_val", response_sample, "abc-def")
    extractor = agent.run_tdd_loop(max_attempts=1)
    
    assert extractor is None
