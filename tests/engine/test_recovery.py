import pytest
import httpx
from pathlib import Path
from har_reproducer.engine import Engine
from har_reproducer.models import Step, StepRequest, StepResponse
from har_reproducer.parser import HARParser

@pytest.fixture
def mock_har(tmp_path):
    har_path = tmp_path / "test.har"
    har_content = {
        "log": {
            "entries": [
                {
                    "request": {
                        "method": "GET",
                        "url": "http://api.example.com/data",
                        "headers": [{"name": "Authorization", "value": "Bearer old_token"}],
                        "cookies": [],
                        "queryString": []
                    },
                    "response": {
                        "status": 200,
                        "content": {"text": "success"}
                    }
                }
            ]
        }
    }
    import json
    har_path.write_text(json.dumps(har_content))
    return har_path

@pytest.mark.parametrize("status_code", [401])
def test_recovery_401_retry(httpx_mock, mock_har, tmp_path, status_code):
    """Test that a 401 response triggers a retry after token update."""
    output_dir = tmp_path / "output"
    engine = Engine(mock_har, output_dir)
    
    # Mock server: first call 401, second call 200
    httpx_mock.add_response(httpx.Response(status_code, content=b"Unauthorized"))
    httpx_mock.add_response(httpx.Response(200, content=b"Success"))
    
    # We need a step to execute
    step = Step(
        index=0,
        request=StepRequest(
            url="http://api.example.com/data",
            method="GET",
            headers={"Authorization": "Bearer old_token"}
        )
    )
    
    _, response = engine.execute_step(step)
    
    # If recovery is implemented, it should eventually return 200
    assert response.status_code == 200

def test_recovery_400_handling(httpx_mock, tmp_path):
    """Test that 400 Bad Request is handled deterministically and returns 400 after retry."""
    output_dir = tmp_path / "output"
    engine = Engine(Path("dummy.har"), output_dir)
    
    # Use add_response for every attempt. 
    # First attempt -> 400, Second attempt (retry) -> 400
    httpx_mock.add_response(httpx.Response(400, content=b"Bad Request"))
    httpx_mock.add_response(httpx.Response(400, content=b"Bad Request"))
    
    step = Step(
        index=0,
        request=StepRequest(
            url="http://api.example.com/data",
            method="GET"
        )
    )
    
    _, response = engine.execute_step(step)
    assert response.status_code == 400
