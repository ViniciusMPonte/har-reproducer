import pytest
from har_reproducer.agents.css_agent import CSSAgent

def test_css_agent_success():
    response_sample = {"body": '<html><body><div class="token_val">abc-def</div></body></html>'}
    agent = CSSAgent("tok_hash", response_sample, "abc-def", path="body")
    extractor = agent.run_tdd_loop()
    
    assert extractor is not None
    assert extractor.verified is True
    assert extractor.agent_type == "CSSAgent"

def test_css_agent_value_in_attribute():
    # Value lives in an attribute, not in the element text.
    response_sample = {
        "body": '<html><body><input type="hidden" name="csrf" value="abc-def"></body></html>'
    }
    agent = CSSAgent("tok_hash", response_sample, "abc-def", path="body")
    extractor = agent.run_tdd_loop()

    assert extractor is not None
    assert extractor.verified is True

def test_css_agent_id_preferred():
    response_sample = {
        "body": '<html><body><span id="csrf" class="x">abc-def</span>'
                '<span class="x">noise</span></body></html>'
    }
    agent = CSSAgent("tok_hash", response_sample, "abc-def", path="body")
    extractor = agent.run_tdd_loop()

    assert extractor is not None
    assert "#csrf" in extractor.code

def test_css_agent_failure():
    response_sample = {"body": '<html><body><div>No token here</div></body></html>'}
    agent = CSSAgent("tok_hash", response_sample, "abc-def", path="body")
    extractor = agent.run_tdd_loop(max_attempts=1)
    
    assert extractor is None
