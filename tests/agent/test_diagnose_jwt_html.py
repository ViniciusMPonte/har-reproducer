import pytest
from pathlib import Path
from har_reproducer.engine import Engine
from har_reproducer.models import PatchAction

def test_diagnose_jwt_in_html(tmp_path):
    """
    Test that the diagnose agent can find a JWT in an HTML body 
    and suggest a fix when a step fails.
    """
    # Setup a simulated failure scenario
    # 1. A response containing a JWT in HTML
    res_dir = tmp_path / "real_responses"
    res_dir.mkdir()
    res_file = res_dir / "res_0000.json"
    res_file.write_text('{"status_code": 200, "body": "<html><body>Token: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...</body></html>"}')
    
    # 2. A failed step that needs this token
    engine = Engine(Path("dummy.har"), tmp_path)
    engine.real_responses_dir = res_dir
    
    # We simulate a failure context
    # For now, we just test that engine.diagnose returns a patch with a regex/css extractor
    patch = engine.diagnose(step_index=1)
    
    assert patch is not None
    assert patch.action == "FIX_EXTRACTOR" or patch.action == "REPLACE_EXTRACTOR"
    assert "eyJ" in patch.new_code or "regex" in patch.new_code.lower()
    assert "token" in patch.target_token_id.lower()
