from typing import Any, Dict, Optional

from har_reproducer.models import TokenLocation
from har_reproducer.tracking.token_location_detector import TokenLocationDetector


def test_find_detects_header() -> None:
    location: Optional[TokenLocation] = TokenLocationDetector.find("tok", {"headers": {"X-Csrf": "tok"}})

    assert location == TokenLocation.HEADER


def test_find_detects_cookie() -> None:
    location: Optional[TokenLocation] = TokenLocationDetector.find("tok", {"cookies": {"sid": "tok"}})

    assert location == TokenLocation.COOKIE


def test_find_detects_redirect_url() -> None:
    location: Optional[TokenLocation] = TokenLocationDetector.find("tok", {"redirect_url": "https://x?tok=tok"})

    assert location == TokenLocation.URL_PARAM


def test_find_detects_json_body_by_content_without_mime() -> None:
    sample: Dict[str, Any] = {"body": '{"csrf":"tok"}', "body_mime": None}

    location: Optional[TokenLocation] = TokenLocationDetector.find("tok", sample)

    assert location == TokenLocation.BODY_JSON


def test_find_detects_html_body() -> None:
    sample: Dict[str, Any] = {"body": "<html><body>tok</body></html>", "body_mime": "text/html"}

    location: Optional[TokenLocation] = TokenLocationDetector.find("tok", sample)

    assert location == TokenLocation.BODY_HTML


def test_find_detects_value_inside_script_block() -> None:
    sample: Dict[str, Any] = {
        "body": "<html><script>var x='tok';</script></html>",
        "body_mime": "text/html",
    }

    location: Optional[TokenLocation] = TokenLocationDetector.find("tok", sample)

    assert location == TokenLocation.SCRIPT


def test_find_returns_none_when_value_not_found_anywhere() -> None:
    location: Optional[TokenLocation] = TokenLocationDetector.find("tok", {})

    assert location is None
