import subprocess
from pathlib import Path
from typing import List, Optional

import pytest

from har_reproducer.fs_io.workspace import Workspace
from har_reproducer.models import StepResponse
from har_reproducer.reproduction.curl_http_transport import CurlHttpTransport
from tests.support.fake_sleeper import FakeSleeper


def _transport(tmp_path: Path, ca_cert_path: Optional[Path], sleeper: FakeSleeper) -> CurlHttpTransport:
    return CurlHttpTransport(Workspace(tmp_path), 8080, ca_cert_path, sleeper)


def test_tls_flag_is_insecure_without_ca_cert(tmp_path: Path) -> None:
    transport: CurlHttpTransport = _transport(tmp_path, None, FakeSleeper())

    assert transport._tls_flag() == "--insecure"


def test_tls_flag_uses_cacert_when_provided(tmp_path: Path) -> None:
    transport: CurlHttpTransport = _transport(tmp_path, Path("/tmp/ca.pem"), FakeSleeper())

    assert transport._tls_flag() == "--cacert /tmp/ca.pem"


def test_build_curl_command_includes_proxy_and_sS_flag(tmp_path: Path) -> None:
    transport: CurlHttpTransport = _transport(tmp_path, None, FakeSleeper())

    command: str = transport._build_curl_command("curl -X GET https://x")

    assert "--proxy http://127.0.0.1:8080" in command
    assert command.strip().endswith("-sS")


def test_decode_stderr_strips_and_decodes_bytes(tmp_path: Path) -> None:
    completed: subprocess.CompletedProcess = subprocess.CompletedProcess(args=[], returncode=1, stderr=b"erro\n")

    assert CurlHttpTransport._decode_stderr(completed) == "erro"


def test_build_error_response_has_zero_status_and_message_as_body() -> None:
    response: StepResponse = CurlHttpTransport._build_error_response(3, "timeout")

    assert response.status_code == 0
    assert response.body == "timeout"


def test_read_captured_response_retries_until_capture_appears(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sleeper: FakeSleeper = FakeSleeper()
    transport: CurlHttpTransport = _transport(tmp_path, None, sleeper)
    attempts: List[Optional[StepResponse]] = [None, None, StepResponse(status_code=200)]

    def fake_try_read_capture(step_index: int) -> Optional[StepResponse]:
        return attempts.pop(0)

    monkeypatch.setattr(transport, "_try_read_capture", fake_try_read_capture)

    response: Optional[StepResponse] = transport._read_captured_response(0)

    assert response is not None and response.status_code == 200
    assert len(sleeper.calls) == 2


def test_read_captured_response_gives_up_after_max_attempts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sleeper: FakeSleeper = FakeSleeper()
    transport: CurlHttpTransport = _transport(tmp_path, None, sleeper)

    monkeypatch.setattr(transport, "_try_read_capture", lambda step_index: None)

    response: Optional[StepResponse] = transport._read_captured_response(0)

    assert response is None
    assert len(sleeper.calls) == CurlHttpTransport.CAPTURE_READ_ATTEMPTS == 5
