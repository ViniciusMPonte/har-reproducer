import pytest
from pathlib import Path
from har_reproducer.parser import HARParser
from tests.conftest import load_fixture

def test_split_har_structure(tmp_steps_dir, load_fixture):
    # Create a temporary HAR file
    har_content = load_fixture("simple_flow.har")
    import json
    har_path = tmp_steps_dir.parent / "test.har"
    har_path.write_text(json.dumps(har_content))
    
    count = HARParser.split_har(har_path, tmp_steps_dir)
    
    assert count == 2
    # Check if files exist
    assert (tmp_steps_dir / "req_0000.json").exists()
    assert (tmp_steps_dir / "res_0000.json").exists()
    assert (tmp_steps_dir / "req_0001.json").exists()
    assert (tmp_steps_dir / "res_0001.json").exists()
    
    # Verify content of one file
    import json
    req_0 = json.loads((tmp_steps_dir / "req_0000.json").read_text())
    assert req_0["url"] == "https://api.example.com/user"
