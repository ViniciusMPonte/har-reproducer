import pytest
from har_reproducer.parser import HARParser
from tests.conftest import load_fixture

def test_options_request_is_skippable(load_fixture):
    har_data = load_fixture("simple_flow.har")
    entry = har_data["log"]["entries"][1] # This is an OPTIONS request
    
    step = HARParser.parse_entry(entry, 1)
    
    assert step.request.method == "OPTIONS"
    assert step.request.is_skippable is True

def test_get_request_is_not_skippable(load_fixture):
    har_data = load_fixture("simple_flow.har")
    entry = har_data["log"]["entries"][0] # This is a GET request
    
    step = HARParser.parse_entry(entry, 0)
    
    assert step.request.method == "GET"
    assert step.request.is_skippable is False
