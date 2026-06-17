import os
from pathlib import Path
from har_reproducer.engine import Engine
from har_reproducer.models import Step, StepRequest
from har_reproducer.session import SessionStore
import httpx
from unittest.mock import MagicMock, patch

def test_token_tracing():
    # Setup paths
    output_dir = Path("test_output")
    output_dir.mkdir(exist_ok=True)
    
    har_path = Path("test.har")
    har_path.write_text('{"log": {"entries": [{"request": {"method": "GET", "url": "http://api.com"}, "response": {"status": 200, "content": {"text": "OK"}}}]}}')
    
    engine = Engine(har_path=har_path, output_dir=output_dir)
    
    # Add some tokens to the session store
    engine.session_store.set_token("auth_token", "secret_abc")
    engine.session_store.set_token("session_id", "sess_123")
    
    # Mock an extractor to give us an origin step
    from har_reproducer.models import Extractor
    engine.session_store.state.registry["auth_token"] = Extractor(
        token_id="auth_token", code="...", agent_type="HeaderAgent", origin_step=0
    )
    engine.session_store.state.registry["session_id"] = Extractor(
        token_id="session_id", code="...", agent_type="CookieAgent", origin_step=1
    )
    
    step = Step(
        index=2,
        request=StepRequest(
            url="https://api.example.com/test",
            method="POST",
            headers={"Authorization": "Bearer secret_abc"},
            cookies={"JSESSIONID": "sess_123"},
            body='{"token": "secret_abc"}'
        )
    )
    
    with patch("httpx.Client.request") as mock_request:
        mock_request.return_value = MagicMock(status_code=200, headers={}, text="OK")
        engine.execute_step(step)
    
    filename = "curls/req_0002.curl.sh"
    if os.path.exists(filename):
        print(f"File {filename} created.")
        with open(filename, "r") as f:
            content = f.read()
            print("Content:\n", content)
            # Verify traces are present
            if "Token auth_token comes from response of step 0" in content and                "Token session_id comes from response of step 1" in content:
                print("SUCCESS: All traces found!")
            else:
                print("FAILURE: Missing traces!")
                exit(1)
    else:
        print(f"File {filename} NOT created!")
        exit(1)

if __name__ == "__main__":
    test_token_tracing()
