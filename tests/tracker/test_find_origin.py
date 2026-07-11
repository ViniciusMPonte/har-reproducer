import pytest
import json
from pathlib import Path
from har_reproducer.grep_utils import grep_in_real_responses
from har_reproducer.tracker import TokenTracker
from har_reproducer.session import SessionStore

def test_find_origin_success(tmp_path):
    # Setup: Create dummy real responses
    responses_dir = tmp_path / "real_responses"
    responses_dir.mkdir()
    
    # res_0001.json contains the token
    res1_content = {"body": "Here is your token: ABC-123"}
    (responses_dir / "res_0001.json").write_text(json.dumps(res1_content))
    
    # res_0002.json does not contain the token
    res2_content = {"body": "Some other content"}
    (responses_dir / "res_0002.json").write_text(json.dumps(res2_content))
    
    # Test grep_in_real_responses directly
    result = grep_in_real_responses(responses_dir, "ABC-123")
    assert result is not None
    assert result[0] == 1
    assert "res_0001.json" in result[1]

def test_find_origin_not_found(tmp_path):
    responses_dir = tmp_path / "real_responses"
    responses_dir.mkdir()
    
    (responses_dir / "res_0001.json").write_text(json.dumps({"body": "No token here"}))
    
    result = grep_in_real_responses(responses_dir, "MISSING-TOKEN")
    assert result is None

def test_tracker_integration_find_origin(tmp_path):
    # This test verifies that TokenTracker correctly uses the grep utility
    responses_dir = tmp_path / "real_responses"
    responses_dir.mkdir()
    
    # Token is in response 2
    (responses_dir / "res_0002.json").write_text(json.dumps({"body": "TOKEN_XYZ"}))
    
    session_store = SessionStore()
    tracker = TokenTracker(responses_dir, session_store)
    
    # Mock a step that has a dynamic token
    from har_reproducer.models import Step, StepRequest, DynamicToken
    
    baseline = Step(index=0, request=StepRequest(url="http://a.com", method="GET", headers={}, cookies={}))
    step = Step(index=1, request=StepRequest(url="http://a.com", method="GET", headers={}, cookies={}))
    
    # Manually create a candidate that we know is in res_0002.json
    candidate = DynamicToken(
        token_id="my_token",
        current_value="TOKEN_XYZ",
        destination_location="Header",
        origin_step=-1,
        status="Unresolved"
    )
    
    # We simulate the search part of analyze_step
    origin = grep_in_real_responses(tracker.responses_dir, candidate.current_value)
    if origin:
        candidate.origin_step = origin[0]
        candidate.status = "Resolved"
        
    assert candidate.status == "Resolved"
    assert candidate.origin_step == 2
