import os
from pathlib import Path
from har_reproducer.engine import Engine
from har_reproducer.models import Step, StepRequest
import httpx
from unittest.mock import MagicMock, patch

def test_recording():
    # Setup paths
    output_dir = Path("test_output")
    output_dir.mkdir(exist_ok=True)
    
    # We need a dummy HAR file for the Engine
    har_path = Path("test.har")
    har_path.write_text('{"log": {"entries": [{"request": {"method": "GET", "url": "http://api.com"}, "response": {"status": 200, "content": {"text": "OK"}}}]}}')
    
    engine = Engine(har_path=har_path, output_dir=output_dir)
    
    step = Step(
        index=1,
        request=StepRequest(
            url="https://api.example.com/test",
            method="POST",
            headers={"Content-Type": "application/json", "X-Test": "Value"},
            cookies={"session": "123"},
            body='{"key": "value"}'
        )
    )
    
    with patch("httpx.Client.request") as mock_request:
        mock_request.return_value = MagicMock(status_code=200, headers={}, text="OK")
        engine.execute_step(step)
    
    # Note: Engine might save curls in output_dir/curls or just curls/
    # Based on my implementation: os.makedirs("curls", exist_ok=True)
    filename = "curls/req_0001.curl.sh"
    if os.path.exists(filename):
        print(f"File {filename} created.")
        with open(filename, "r") as f:
            print("Content:\n", f.read())
    else:
        print(f"File {filename} NOT created!")
        exit(1)

if __name__ == "__main__":
    test_recording()
