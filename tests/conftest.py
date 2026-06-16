import pytest
import json
from pathlib import Path

@pytest.fixture
def tmp_steps_dir(tmp_path):
    """Provides a temporary directory for step files."""
    d = tmp_path / "steps"
    d.mkdir()
    return d

@pytest.fixture
def tmp_real_responses_dir(tmp_path):
    """Provides a temporary directory for real responses."""
    d = tmp_path / "real_responses"
    d.mkdir()
    return d

@pytest.fixture
def load_fixture():
    """Helper to load fixture files from the tests/fixtures directory."""
    def _load(path_relative_to_fixtures):
        fixture_path = Path(__file__).parent / "fixtures" / path_relative_to_fixtures
        if not fixture_path.exists():
            raise FileNotFoundError(f"Fixture not found: {fixture_path}")
        
        if fixture_path.suffix == ".json":
            with open(fixture_path, "r", encoding="utf-8") as f:
                return json.load(f)
        
        return fixture_path.read_text(encoding="utf-8")
        
    return _load
