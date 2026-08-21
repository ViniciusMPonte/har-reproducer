from pathlib import Path
from typing import List

import pytest

from tests.support.cli_invocation_result import CliInvocationResult
from tests.support.cli_invoker import CliInvoker
from tests.support.replay_scenario import ReplayScenario
from tests.test_cli_replay import (
    canned_http_server,
    main_workspace,
    network_session_dir,
)


def test_optimize_requires_success_criteria(cli_invoker: CliInvoker, tmp_path: Path) -> None:
    output_dir: Path = tmp_path / "ws_with_curls"
    (output_dir / "curls").mkdir(parents=True)
    (output_dir / "curls" / "req_0000.curl.sh").touch()

    result: CliInvocationResult = cli_invoker.invoke(["optimize", "--output", str(output_dir), "--to", "0"])

    assert isinstance(result.exception, ValueError)
    assert "success_criteria" in str(result.exception)


def test_optimize_rejects_missing_from_index(cli_invoker: CliInvoker, tmp_path: Path) -> None:
    output_dir: Path = tmp_path / "ws_with_curls"
    (output_dir / "curls").mkdir(parents=True)
    (output_dir / "curls" / "req_0000.curl.sh").touch()

    result: CliInvocationResult = cli_invoker.invoke([
        "optimize", "--output", str(output_dir), "--to", "0", "--from", "999",
        "--success-criteria", '[{"type":"status_code","expected":200}]',
    ])

    assert isinstance(result.exception, ValueError)
    assert "999" in str(result.exception)


def test_optimize_success_criteria_flag_overrides_empty_config(cli_invoker: CliInvoker, tmp_path: Path) -> None:
    output_dir: Path = tmp_path / "ws_with_curls"
    (output_dir / "curls").mkdir(parents=True)
    (output_dir / "curls" / "req_0000.curl.sh").touch()

    result: CliInvocationResult = cli_invoker.invoke([
        "optimize", "--output", str(output_dir), "--to", "0", "--from", "999",
        "--success-criteria", '[{"type":"status_code","expected":200}]',
    ])

    assert isinstance(result.exception, ValueError)
    assert "success_criteria" not in str(result.exception)


@pytest.mark.slow
def test_optimize_happy_path_writes_default_steps_file(
        cli_invoker: CliInvoker, main_workspace: Path, tmp_path: Path,
) -> None:
    scenario: ReplayScenario = ReplayScenario(cli_invoker, main_workspace, tmp_path)

    result: CliInvocationResult = cli_invoker.invoke([
        "optimize", "--output", str(scenario.workspace), "--to", "9",
        "--success-criteria", '[{"type":"status_code","expected":200}]',
    ])

    assert result.exception is None
    assert "Optimization SUCCESSFUL" in result.stdout
    steps_files: List[Path] = list((scenario.workspace / "replays").glob("optimized_*.txt"))
    assert len(steps_files) == 1
    assert steps_files[0].read_text(encoding="utf-8").splitlines() == ["0", "9"]


@pytest.mark.slow
def test_optimize_failed_exits_with_code_1(
        cli_invoker: CliInvoker, main_workspace: Path, tmp_path: Path,
) -> None:
    scenario: ReplayScenario = ReplayScenario(cli_invoker, main_workspace, tmp_path)

    result: CliInvocationResult = cli_invoker.invoke([
        "optimize", "--output", str(scenario.workspace), "--to", "9",
        "--success-criteria", '[{"type":"status_code","expected":599}]',
    ])

    assert "Optimization FAILED: unable to find a passing subset" in result.stdout
    assert isinstance(result.exception, SystemExit)
    assert result.exception.code == 1


@pytest.mark.slow
def test_optimize_respects_custom_steps_out(
        cli_invoker: CliInvoker, main_workspace: Path, tmp_path: Path,
) -> None:
    scenario: ReplayScenario = ReplayScenario(cli_invoker, main_workspace, tmp_path)
    custom_output: Path = tmp_path / "custom_optimized.txt"

    result: CliInvocationResult = cli_invoker.invoke([
        "optimize", "--output", str(scenario.workspace), "--to", "9",
        "--success-criteria", '[{"type":"status_code","expected":200}]',
        "--steps-out", str(custom_output),
    ])

    assert result.exception is None
    assert custom_output.read_text(encoding="utf-8").splitlines() == ["0", "9"]
    assert not list((scenario.workspace / "replays").glob("optimized_*.txt"))
