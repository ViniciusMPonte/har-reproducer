import base64
from typing import Any, Dict, List

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


def _entry(status: int, content: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "request": {"url": "https://x", "method": "GET", "headers": [], "cookies": []},
        "response": {"status": status, "headers": [], "cookies": [], "content": content},
    }


def test_entries_missing_response_body_counts_bodyless_entries_with_ordinary_status() -> None:
    entries: List[Dict[str, Any]] = [
        _entry(200, {"text": "corpo"}),
        _entry(200, {"text": ""}),
        _entry(404, {}),
    ]

    assert HARParser.entries_missing_response_body(entries) == 2


def test_entries_missing_response_body_ignores_status_that_never_carries_body() -> None:
    entries: List[Dict[str, Any]] = [_entry(304, {}), _entry(204, {}), _entry(101, {})]

    assert HARParser.entries_missing_response_body(entries) == 0


def test_entries_missing_response_body_counts_absent_text_and_empty_text_alike() -> None:
    assert HARParser.entries_missing_response_body([_entry(200, {})]) == 1
    assert HARParser.entries_missing_response_body([_entry(200, {"text": ""})]) == 1


def test_entries_missing_response_body_is_zero_when_every_entry_has_a_body() -> None:
    entries: List[Dict[str, Any]] = [_entry(200, {"text": "a"}), _entry(304, {"text": "b"})]

    assert HARParser.entries_missing_response_body(entries) == 0


def test_entries_missing_response_body_handles_entry_without_content_key() -> None:
    entry: Dict[str, Any] = {
        "request": {"url": "https://x", "method": "GET", "headers": [], "cookies": []},
        "response": {"status": 200, "headers": [], "cookies": []},
    }

    assert HARParser.entries_missing_response_body([entry]) == 1
