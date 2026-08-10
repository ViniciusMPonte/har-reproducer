import os
import subprocess
from pathlib import Path
from typing import List

from har_reproducer.fs_io.workspace import Workspace
from har_reproducer.reproduction.mitm_env import MitmEnv
from har_reproducer.reproduction.mitm_proxy_orchestrator import MitmProxyOrchestrator
from tests.support.fake_process import FakeProcess


def _orchestrator(tmp_path: Path) -> MitmProxyOrchestrator:
    return MitmProxyOrchestrator(Workspace(tmp_path), proxy_port=8080, confdir=tmp_path)


def test_build_command_includes_port_and_addon_path(tmp_path: Path) -> None:
    orchestrator: MitmProxyOrchestrator = _orchestrator(tmp_path)

    command: List[str] = orchestrator._build_command()

    assert str(orchestrator.port) in command
    assert str(MitmProxyOrchestrator.ADDON_PATH) in command


def test_build_command_sets_confdir_to_confdir_argument(tmp_path: Path) -> None:
    orchestrator: MitmProxyOrchestrator = _orchestrator(tmp_path)

    command: List[str] = orchestrator._build_command()

    assert f"confdir={tmp_path}" in command


def test_ca_cert_path_is_derived_from_confdir(tmp_path: Path) -> None:
    orchestrator: MitmProxyOrchestrator = _orchestrator(tmp_path)

    assert orchestrator.ca_cert_path == tmp_path / MitmProxyOrchestrator.CA_CERT_FILENAME


def test_build_env_includes_capture_path(tmp_path: Path) -> None:
    orchestrator: MitmProxyOrchestrator = _orchestrator(tmp_path)

    env: dict = orchestrator._build_env()

    assert env[MitmEnv.CAPTURE_PATH_ENV_VAR] == str(orchestrator.workspace.mitm_capture_file())


def test_prepend_package_root_without_existing_pythonpath() -> None:
    result: str = MitmProxyOrchestrator._prepend_package_root(None)

    assert result == str(MitmProxyOrchestrator.PACKAGE_ROOT)


def test_prepend_package_root_prepends_to_existing_pythonpath() -> None:
    result: str = MitmProxyOrchestrator._prepend_package_root("/outro")

    assert result == f"{MitmProxyOrchestrator.PACKAGE_ROOT}{os.pathsep}/outro"


def test_resolve_port_uses_explicit_port_without_opening_socket(tmp_path: Path) -> None:
    orchestrator: MitmProxyOrchestrator = _orchestrator(tmp_path)

    assert orchestrator.port == 8080


def test_build_early_exit_message_handles_missing_log_file(tmp_path: Path) -> None:
    orchestrator: MitmProxyOrchestrator = _orchestrator(tmp_path)
    orchestrator._process = FakeProcess(returncode=1)

    message: str = orchestrator._build_early_exit_message()

    assert "exit code 1" in message


def test_terminate_calls_terminate_and_not_kill_when_process_exits_cleanly(tmp_path: Path) -> None:
    orchestrator: MitmProxyOrchestrator = _orchestrator(tmp_path)
    process: FakeProcess = FakeProcess(returncode=0)
    orchestrator._process = process

    orchestrator._terminate()

    assert process.terminate_calls == 1
    assert process.kill_calls == 0
    assert orchestrator._process is None


def test_terminate_kills_process_after_timeout_expired(tmp_path: Path) -> None:
    orchestrator: MitmProxyOrchestrator = _orchestrator(tmp_path)
    process: FakeProcess = FakeProcess(
        returncode=0, wait_side_effects=[subprocess.TimeoutExpired(cmd=["mitmdump"], timeout=5.0)]
    )
    orchestrator._process = process

    orchestrator._terminate()

    assert process.kill_calls == 1
    assert len(process.wait_calls) == 2


def test_terminate_is_a_no_op_without_process(tmp_path: Path) -> None:
    orchestrator: MitmProxyOrchestrator = _orchestrator(tmp_path)
    orchestrator._process = None

    orchestrator._terminate()

    assert orchestrator._process is None
