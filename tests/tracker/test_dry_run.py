import pytest
from pathlib import Path
from har_reproducer.engine import Engine
from har_reproducer.parser import HARParser
import json

def test_dry_run_simulation(tmp_path):
    # Setup: Create a temporary HAR file
    har_content = {
        "log": {
            "entries": [
                {
                    "request": {
                        "method": "GET",
                        "url": "https://api.example.com/1",
                        "headers": [],
                        "cookies": [],
                        "postData": None
                    },
                    "response": {
                        "status": 200,
                        "headers": [],
                        "cookies": [],
                        "content": { "text": "Initial Response" },
                        "redirectUrl": None
                    }
                },
                {
                    "request": {
                        "method": "GET",
                        "url": "https://api.example.com/2",
                        "headers": [{"name": "X-Token", "value": "TOKEN_A"}],
                        "cookies": [],
                        "postData": None
                    },
                    "response": {
                        "status": 200,
                        "headers": [],
                        "cookies": [],
                        "content": { "text": "Second Response" },
                        "redirectUrl": None
                    }
                }
            ]
        }
    }
    har_path = tmp_path / "test_dry.har"
    har_path.write_text(json.dumps(har_content))
    
    output_dir = tmp_path / "output"
    engine = Engine(har_path, output_dir)
    
    # Run in dry-run mode
    # Dry-run should not create real_responses files
    engine.run(dry_run=True)
    
    # Verify that no real responses were saved to disk
    # Since dry-run uses HAR responses, it shouldn't write to real_responses_dir
    # unless we explicitly design it to save the simulated ones.
    # Based on current Engine implementation, it skips the 'save real response' block.
    res_dir = output_dir / "real_responses"
    if res_dir.exists():
        assert len(list(res_dir.glob("*.json"))) == 0
