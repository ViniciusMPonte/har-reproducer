import base64
from typing import Any, Dict

from har_reproducer.fs_io.har_parser import HARParser
from har_reproducer.models import Step


def test_decode_body_empty_content_returns_empty_string() -> None:
    assert HARParser.decode_body("", encoding=None) == ""


def test_decode_body_decodes_valid_base64() -> None:
    encoded: str = base64.b64encode(b"ok").decode("ascii")

    assert HARParser.decode_body(encoded, encoding="base64") == "ok"


def test_decode_body_falls_back_to_original_on_invalid_base64() -> None:
    assert HARParser.decode_body("!!!not-base64!!!", encoding="base64") == "!!!not-base64!!!"


def test_parse_entry_builds_step_from_minimal_har_entry() -> None:
    entry: Dict[str, Any] = {
        "request": {"url": "https://x", "method": "GET", "headers": [], "cookies": []},
        "response": {
            "status": 200,
            "headers": [],
            "cookies": [],
            "content": {"text": "body", "mimeType": "text/plain"},
        },
    }

    step: Step = HARParser.parse_entry(entry, 3)

    assert step.index == 3
    assert step.request.url == "https://x"
    assert step.response is not None
    assert step.response.status_code == 200
    assert step.response.body == "body"


def test_parse_entry_extracts_post_data_as_request_body() -> None:
    entry: Dict[str, Any] = {
        "request": {
            "url": "https://x",
            "method": "POST",
            "headers": [],
            "cookies": [],
            "postData": {"text": "payload"},
        },
        "response": {"status": 200, "headers": [], "cookies": [], "content": {}},
    }

    step: Step = HARParser.parse_entry(entry, 0)

    assert step.request.body == "payload"
