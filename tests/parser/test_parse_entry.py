import pytest
from har_reproducer.parser import HARParser
from tests.conftest import load_fixture

def test_parse_entry_basic(load_fixture):
    har_data = load_fixture("simple_flow.har")
    entry = har_data["log"]["entries"][0]
    
    step = HARParser.parse_entry(entry, 0)
    
    assert step.index == 0
    assert step.request.url == "https://api.example.com/user"
    assert step.request.method == "GET"
    assert step.request.headers["Accept"] == "application/json"
    assert step.response.status_code == 200
    assert step.response.body == '{"id": 1, "name": "Test User"}'
    assert step.response.cookies["session_id"] == "12345"

def test_parse_entry_options_skippable(load_fixture):
    har_data = load_fixture("simple_flow.har")
    entry = har_data["log"]["entries"][1] # OPTIONS request
    
    step = HARParser.parse_entry(entry, 1)
    
    assert step.request.method == "OPTIONS"
    assert step.request.is_skippable is True
