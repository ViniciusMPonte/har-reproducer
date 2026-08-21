import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterator, List

import pytest

from tests.support.auth_flow_tokens import AuthFlowTokens
from tests.support.canned_http_server import CannedHttpServer


class CannedHttpHandlerFixture:
    FIXTURES_DIR: Path = Path(__file__).parent.parent / "fixtures"


@pytest.fixture(scope="module")
def canned_server() -> Iterator[CannedHttpServer]:
    server: CannedHttpServer = CannedHttpServer(CannedHttpServer.free_port())
    server.start()
    yield server
    server.stop()


def _get(server: CannedHttpServer, path: str) -> str:
    with urllib.request.urlopen(f"http://127.0.0.1:{server.port}{path}") as response:
        return response.read().decode("utf-8")


def _har_entries() -> List[Dict[str, Any]]:
    har_path: Path = CannedHttpHandlerFixture.FIXTURES_DIR / "synthetic_flow.har"
    return json.loads(har_path.read_text(encoding="utf-8"))["log"]["entries"]


def _har_response_header(entry_index: int, header_name: str) -> str:
    for header in _har_entries()[entry_index]["response"]["headers"]:
        if header["name"] == header_name:
            return header["value"]
    raise AssertionError(f"header {header_name!r} not found in entry {entry_index}")


def _har_response_body(entry_index: int) -> str:
    return _har_entries()[entry_index]["response"]["content"]["text"]


def test_item_route_matches_the_exact_har_path_by_prefix(canned_server: CannedHttpServer) -> None:
    body: str = _get(canned_server, "/item/4242")

    assert json.loads(body) == {"id": 9999}


def test_item_route_matches_any_other_suffix_the_same_way(canned_server: CannedHttpServer) -> None:
    assert _get(canned_server, "/item/4242") == _get(canned_server, "/item/9999")


def test_other_routes_remain_served_by_exact_lookup(canned_server: CannedHttpServer) -> None:
    body: str = _get(canned_server, "/login")

    assert "tok_CSS_9" in body


def test_session_id_cookie_diverges_from_the_har(canned_server: CannedHttpServer) -> None:
    har_cookie: str = _har_response_header(0, "Set-Cookie")
    with urllib.request.urlopen(f"http://127.0.0.1:{canned_server.port}/login") as response:
        live_cookie: str = response.headers["Set-Cookie"]

    assert "SESSIONID=abc123sess" in har_cookie
    assert "SESSIONID=abc123live" in live_cookie
    assert har_cookie != live_cookie


def test_css_marker_and_script_nonce_diverge_from_the_har(canned_server: CannedHttpServer) -> None:
    har_body: str = _har_response_body(0)
    live_body: str = _get(canned_server, "/login")

    assert "tok_CSS_1" in har_body and "tok_CSS_9" in live_body
    assert "scr_NONCE_2" in har_body and "scr_NONCE_9" in live_body


def test_plain_value_diverges_from_the_har(canned_server: CannedHttpServer) -> None:
    har_body: str = _har_response_body(5)
    live_body: str = _get(canned_server, "/plain")

    assert har_body == "PLAINVAL777"
    assert live_body == "PLAINVAL999"


def _har_response_cookie(entry_index: int, cookie_name: str) -> str:
    for cookie in _har_entries()[entry_index]["response"]["cookies"]:
        if cookie["name"] == cookie_name:
            return cookie["value"]
    raise AssertionError(f"cookie {cookie_name!r} not found in entry {entry_index}")


def test_prefs_cookie_diverges_from_the_har(canned_server: CannedHttpServer) -> None:
    har_cookie: str = _har_response_cookie(7, "PREFS")
    with urllib.request.urlopen(f"http://127.0.0.1:{canned_server.port}/prefs") as response:
        live_cookie: str = response.headers["Set-Cookie"]

    assert har_cookie == "xyz789"
    assert "PREFS=xyz999" in live_cookie


def test_new_header_pair_covers_the_header_agent_without_depending_on_content_type(
        canned_server: CannedHttpServer,
) -> None:
    har_response_value: str = _har_response_header(0, "X-Api-Header")
    har_request_value: str = next(
        header["value"] for header in _har_entries()[3]["request"]["headers"] if header["name"] == "X-Api-Header"
    )
    with urllib.request.urlopen(f"http://127.0.0.1:{canned_server.port}/login") as response:
        live_value: str = response.headers["X-Api-Header"]

    assert har_response_value == har_request_value == "build-42"
    assert live_value == "build-99"


def _get_status(server: CannedHttpServer, path: str, headers: Dict[str, str]) -> int:
    request: urllib.request.Request = urllib.request.Request(
        f"http://127.0.0.1:{server.port}{path}", headers=headers,
    )
    try:
        with urllib.request.urlopen(request) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


def test_login_route_always_serves_the_live_token(canned_server: CannedHttpServer) -> None:
    request: urllib.request.Request = urllib.request.Request(
        f"http://127.0.0.1:{canned_server.port}/login", method="POST", data=b"{}",
    )
    with urllib.request.urlopen(request) as response:
        body: str = response.read().decode("utf-8")

    assert json.loads(body) == {"token": AuthFlowTokens.TOKEN_VIVO}


def test_protected_route_rejects_the_har_recorded_token(canned_server: CannedHttpServer) -> None:
    status: int = _get_status(
        canned_server, "/protected", {"Authorization": f"Bearer {AuthFlowTokens.TOKEN_HAR}"},
    )

    assert status == 403


def test_protected_route_accepts_the_live_token(canned_server: CannedHttpServer) -> None:
    status: int = _get_status(
        canned_server, "/protected", {"Authorization": f"Bearer {AuthFlowTokens.TOKEN_VIVO}"},
    )

    assert status == 200


def test_protected_route_rejects_a_missing_authorization_header(canned_server: CannedHttpServer) -> None:
    status: int = _get_status(canned_server, "/protected", {})

    assert status == 403
