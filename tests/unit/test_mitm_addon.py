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
