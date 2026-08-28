from pathlib import Path
from typing import Tuple

from har_reproducer.fs_io import Workspace
from har_reproducer.models import StepRequest
from har_reproducer.reproduction import RequestUrlScope


def test_parts_extracts_host_port_and_path_with_https_default_port() -> None:
    assert RequestUrlScope.parts("https://exemplo.com/login") == ("exemplo.com", 443, "/login")


def test_parts_extracts_host_port_and_path_with_http_default_port() -> None:
    assert RequestUrlScope.parts("http://exemplo.com/login") == ("exemplo.com", 80, "/login")


def test_parts_prefers_explicit_port_over_scheme_default() -> None:
    assert RequestUrlScope.parts("https://exemplo.com:8443/api") == ("exemplo.com", 8443, "/api")


def test_parts_defaults_path_to_root_when_absent() -> None:
    host, port, path = RequestUrlScope.parts("https://exemplo.com")

    assert path == "/"


def test_parts_resolves_ipv6_host_in_brackets() -> None:
    host, port, path = RequestUrlScope.parts("https://[::1]:9000/x")

    assert host == "::1"
    assert port == 9000
    assert path == "/x"


def test_parts_for_step_reads_request_file_and_matches_parts(tmp_path: Path) -> None:
    workspace: Workspace = Workspace(tmp_path)
    workspace.request_file(0).write_text(
        StepRequest(url="https://exemplo.com:8443/api", method="GET").model_dump_json(),
        encoding="utf-8",
    )

    result: Tuple[str, int, str] = RequestUrlScope.parts_for_step(workspace, 0)

    assert result == RequestUrlScope.parts("https://exemplo.com:8443/api")
