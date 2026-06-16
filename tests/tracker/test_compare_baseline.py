import pytest
from har_reproducer.tracker import TokenTracker
from har_reproducer.session import SessionStore
from har_reproducer.models import Step, StepRequest, StepResponse
from pathlib import Path

@pytest.fixture
def tracker(tmp_path):
    responses_dir = tmp_path / "real_responses"
    responses_dir.mkdir()
    session_store = SessionStore()
    return TokenTracker(responses_dir, session_store)

def test_compare_baseline_no_diff():
    tracker = TokenTracker(Path("."), SessionStore())
    
    # Baseline and step are identical
    baseline = Step(
        index=0,
        request=StepRequest(url="http://api.com", method="GET", headers={"X-API-Key": "static"}, cookies={})
    )
    step = Step(
        index=1,
        request=StepRequest(url="http://api.com", method="GET", headers={"X-API-Key": "static"}, cookies={})
    )
    
    diffs = tracker._compare_to_baseline(step, baseline)
    assert diffs == {}

def test_compare_baseline_header_diff():
    tracker = TokenTracker(Path("."), SessionStore())
    
    baseline = Step(
        index=0,
        request=StepRequest(url="http://api.com", method="GET", headers={"Authorization": "Bearer initial"}, cookies={})
    )
    step = Step(
        index=1,
        request=StepRequest(url="http://api.com", method="GET", headers={"Authorization": "Bearer updated"}, cookies={})
    )
    
    diffs = tracker._compare_to_baseline(step, baseline)
    assert diffs == {"header:Authorization": "Bearer updated"}

def test_compare_baseline_cookie_diff():
    tracker = TokenTracker(Path("."), SessionStore())
    
    baseline = Step(
        index=0,
        request=StepRequest(url="http://api.com", method="GET", headers={}, cookies={"session": "old"})
    )
    step = Step(
        index=1,
        request=StepRequest(url="http://api.com", method="GET", headers={}, cookies={"session": "new"})
    )
    
    diffs = tracker._compare_to_baseline(step, baseline)
    assert diffs == {"cookie:session": "new"}

def test_compare_baseline_body_diff():
    tracker = TokenTracker(Path("."), SessionStore())
    
    baseline = Step(
        index=0,
        request=StepRequest(url="http://api.com", method="POST", headers={}, cookies={}, body="foo=1")
    )
    step = Step(
        index=1,
        request=StepRequest(url="http://api.com", method="POST", headers={}, cookies={}, body="foo=2")
    )
    
    diffs = tracker._compare_to_baseline(step, baseline)
    assert diffs == {"body": "foo=2"}
