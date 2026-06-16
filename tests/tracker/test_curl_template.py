import pytest
from har_reproducer.tracker import TokenTracker
from har_reproducer.session import SessionStore
from har_reproducer.models import Step, StepRequest
from pathlib import Path

@pytest.fixture
def tracker(tmp_path):
    responses_dir = tmp_path / "real_responses"
    responses_dir.mkdir()
    session_store = SessionStore()
    return TokenTracker(responses_dir, session_store)

def test_generate_curl_template_basic():
    tracker = TokenTracker(Path("."), SessionStore())
    
    request = StepRequest(
        url="https://api.example.com/data",
        method="POST",
        headers={"Authorization": "Bearer secret", "Content-Type": "application/json"},
        cookies={}
    )
    
    template = tracker._generate_curl_template(request)
    
    assert "curl -X POST" in template
    assert "'https://api.example.com/data'" in template
    assert '-H "Authorization: Bearer secret"' in template
    assert '-H "Content-Type: application/json"' in template

def test_generate_curl_template_with_tokens(tracker):
    # Setup session store with tokens
    tracker.session_store.set_token("auth_token", "LIVE_TOKEN_123")
    
    request = StepRequest(
        url="https://api.example.com/data",
        method="GET",
        headers={"Authorization": "{{auth_token}}"},
        cookies={}
    )
    
    # The _generate_curl_template currently just returns the raw string with placeholders
    # because the actual interpolation happens in Engine.execute_step or a render call.
    # However, the contract says it should generate the template.
    template = tracker._generate_curl_template(request)
    
    assert "Authorization: {{auth_token}}" in template
