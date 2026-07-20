import pytest
from har_reproducer.agents.regex_agent import RegexAgent

def test_regex_agent_success():
    response_sample = {"body": "some content token_val=ghi-789 more content"}
    agent = RegexAgent("tok_hash", response_sample, "ghi-789", path="body")
    extractor = agent.run_tdd_loop()
    
    assert extractor is not None
    assert extractor.verified is True
    assert extractor.agent_type == "RegexAgent"

def test_regex_agent_in_script():
    response_sample = {
        "body": '<script>var config = {"csrf": "ghi-789"};</script>'
    }
    agent = RegexAgent("tok_hash", response_sample, "ghi-789", path="body")
    extractor = agent.run_tdd_loop()

    assert extractor is not None
    assert extractor.verified is True

def test_regex_agent_failure():
    response_sample = {"body": "some content without token"}
    agent = RegexAgent("tok_hash", response_sample, "ghi-789", path="body")
    extractor = agent.run_tdd_loop(max_attempts=1)
    
    assert extractor is None
