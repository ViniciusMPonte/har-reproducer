import gzip
import os
from typing import Any, Dict, Optional

import brotli

from har_reproducer.reproduction.mitm_env import MitmEnv

os.environ.setdefault(MitmEnv.CAPTURE_PATH_ENV_VAR, "/tmp/mitm_addon_test_capture.json")

from har_reproducer.reproduction.mitm_addon import MitmAddon
from mitmproxy.http import Response


def _response_with_body(body: bytes, content_encoding: Optional[str] = None) -> Response:
    response: Response = Response.make(200, b"", {"content-type": "text/plain"})
    if content_encoding is not None:
        response.headers["content-encoding"] = content_encoding
    response.raw_content = body
    return response


def test_build_content_decompresses_gzip_body_before_deciding_text_or_base64() -> None:
    original: bytes = b"function loadChart(){return 1;}"
    response: Response = _response_with_body(gzip.compress(original), content_encoding="gzip")

    content: Dict[str, Any] = MitmAddon._build_content(response)

    assert content == {"text": original.decode("utf-8"), "mimeType": "text/plain"}


def test_build_content_decompresses_brotli_body() -> None:
    original: bytes = b"function loadChart(){return 1;}"
    response: Response = _response_with_body(brotli.compress(original), content_encoding="br")

    content: Dict[str, Any] = MitmAddon._build_content(response)

    assert content == {"text": original.decode("utf-8"), "mimeType": "text/plain"}


def test_build_content_falls_back_to_raw_when_content_encoding_is_incoherent() -> None:
    body: bytes = b"nao sou gzip de verdade"
    response_with_bad_encoding: Response = _response_with_body(body, content_encoding="gzip")
    response_without_encoding: Response = _response_with_body(body, content_encoding=None)

    content_with_bad_encoding: Dict[str, Any] = MitmAddon._build_content(response_with_bad_encoding)
    content_without_encoding: Dict[str, Any] = MitmAddon._build_content(response_without_encoding)

    assert content_with_bad_encoding == content_without_encoding


def test_build_content_unchanged_when_no_content_encoding_header() -> None:
    original: bytes = b"texto puro sem compressao"
    response: Response = _response_with_body(original, content_encoding=None)

    content: Dict[str, Any] = MitmAddon._build_content(response)

    assert content == {"text": original.decode("utf-8"), "mimeType": "text/plain"}


def test_build_content_binary_body_without_encoding_still_falls_back_to_base64() -> None:
    original: bytes = bytes(range(256))
    response: Response = _response_with_body(original, content_encoding=None)

    content: Dict[str, Any] = MitmAddon._build_content(response)

    assert content["encoding"] == "base64"


def test_build_content_returns_empty_text_for_empty_body() -> None:
    response: Response = _response_with_body(b"", content_encoding=None)

    content: Dict[str, Any] = MitmAddon._build_content(response)

    assert content == {"text": "", "mimeType": "text/plain"}


def _response_with_set_cookie_headers(*set_cookie_values: str) -> Response:
    response: Response = Response.make(200, b"", {"content-type": "text/plain"})
    for value in set_cookie_values:
        response.headers.add("set-cookie", value)
    return response


def test_response_cookies_list_preserves_domain_and_path() -> None:
    response: Response = _response_with_set_cookie_headers("a=1; Domain=.exemplo.com; Path=/api")

    cookies_list = MitmAddon._response_cookies_list(response)

    assert cookies_list == [
        {"name": "a", "value": "1", "domain": ".exemplo.com", "path": "/api", "expired": False}
    ]


def test_response_cookies_list_marks_max_age_zero_as_expired() -> None:
    response: Response = _response_with_set_cookie_headers("a=1; Max-Age=0")

    cookies_list = MitmAddon._response_cookies_list(response)

    assert cookies_list[0]["expired"] is True


def test_response_cookies_list_defaults_domain_none_and_path_root_when_absent() -> None:
    response: Response = _response_with_set_cookie_headers("a=1")

    cookies_list = MitmAddon._response_cookies_list(response)

    assert cookies_list == [{"name": "a", "value": "1", "domain": None, "path": "/", "expired": False}]


def test_response_cookies_list_produces_one_entry_per_cookie_for_multiple_set_cookie_headers() -> None:
    response: Response = _response_with_set_cookie_headers("a=1", "b=2; Path=/x")

    cookies_list = MitmAddon._response_cookies_list(response)

    assert cookies_list == [
        {"name": "a", "value": "1", "domain": None, "path": "/", "expired": False},
        {"name": "b", "value": "2", "domain": None, "path": "/x", "expired": False},
    ]
