import pytest
from har_reproducer.parser import HARParser
from tests.conftest import load_fixture

def test_decode_body_base64():
    # "SGVsbG8gV29ybGQ=" is "Hello World"
    result = HARParser.decode_body("SGVsbG8gV29ybGQ=", encoding="base64")
    assert result == "Hello World"

def test_decode_body_no_encoding():
    result = HARParser.decode_body("Hello World", encoding=None)
    assert result == "Hello World"

def test_decode_body_invalid_base64():
    # Invalid base64 should return original text
    result = HARParser.decode_body("!!! Not Base64 !!!", encoding="base64")
    assert result == "!!! Not Base64 !!!"
