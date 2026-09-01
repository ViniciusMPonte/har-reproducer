from argparse import ArgumentParser, Namespace
from pathlib import Path
from typing import List, Optional

import pytest

from har_reproducer.cli import CliHandlers, CliParser, ExtractorCliHandlers
from har_reproducer.engines import EngineFactory
from har_reproducer.fs_io import HARParser
from tests.support.cli_invocation_result import CliInvocationResult
from tests.support.cli_invoker import CliInvoker
from tests.support.replay_scenario import ReplayScenario
from tests.test_cli_replay import (
    canned_http_server,
    main_workspace,
    network_session_dir,
)


def _build_optimize_parser() -> ArgumentParser:
    handlers: CliHandlers = CliHandlers(engine_factory=EngineFactory, har_parser=HARParser)
    extractor_handlers: ExtractorCliHandlers = ExtractorCliHandlers()
    return CliParser(handlers, extractor_handlers).build()


def test_optimize_parses_required_steps_file_flag() -> None:
    parser: ArgumentParser = _build_optimize_parser()

    args: Namespace = parser.parse_args([
        "optimize", "--output", "X", "--to", "5", "--required-steps-file", "path.txt",
    ])

    assert args.required_steps_file == "path.txt"


def test_optimize_defaults_required_steps_file_to_none() -> None:
    parser: ArgumentParser = _build_optimize_parser()

    args: Namespace = parser.parse_args(["optimize", "--output", "X", "--to", "5"])

    optional_required_steps_file: Optional[str] = args.required_steps_file
    assert optional_required_steps_file is None


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


def test_optimize_required_steps_file_missing_workspace_index_raises(
        cli_invoker: CliInvoker, tmp_path: Path,
) -> None:
    output_dir: Path = tmp_path / "ws_with_curls"
    (output_dir / "curls").mkdir(parents=True)
    (output_dir / "curls" / "req_0000.curl.sh").touch()
    required_steps_file: Path = tmp_path / "required.txt"
    required_steps_file.write_text("999\n", encoding="utf-8")

    result: CliInvocationResult = cli_invoker.invoke([
        "optimize", "--output", str(output_dir), "--to", "0",
        "--success-criteria", '[{"type":"status_code","expected":200}]',
        "--required-steps-file", str(required_steps_file),
    ])

    assert isinstance(result.exception, ValueError)
    assert "999" in str(result.exception)


def test_optimize_required_steps_file_out_of_range_raises(
        cli_invoker: CliInvoker, tmp_path: Path,
) -> None:
    output_dir: Path = tmp_path / "ws_with_curls"
    (output_dir / "curls").mkdir(parents=True)
    (output_dir / "curls" / "req_0000.curl.sh").touch()
    (output_dir / "curls" / "req_0001.curl.sh").touch()
    required_steps_file: Path = tmp_path / "required.txt"
    required_steps_file.write_text("1\n", encoding="utf-8")

    result: CliInvocationResult = cli_invoker.invoke([
        "optimize", "--output", str(output_dir), "--to", "0",
        "--success-criteria", '[{"type":"status_code","expected":200}]',
        "--required-steps-file", str(required_steps_file),
    ])

    assert isinstance(result.exception, ValueError)
    assert "--from" in str(result.exception)
    assert "--to" in str(result.exception)


def test_optimize_required_steps_file_nonexistent_path_raises(
        cli_invoker: CliInvoker, tmp_path: Path,
) -> None:
    output_dir: Path = tmp_path / "ws_with_curls"
    (output_dir / "curls").mkdir(parents=True)
    (output_dir / "curls" / "req_0000.curl.sh").touch()
    missing_required_steps_file: Path = tmp_path / "does_not_exist.txt"

    result: CliInvocationResult = cli_invoker.invoke([
        "optimize", "--output", str(output_dir), "--to", "0",
        "--success-criteria", '[{"type":"status_code","expected":200}]',
        "--required-steps-file", str(missing_required_steps_file),
    ])

    assert isinstance(result.exception, ValueError)
    assert str(missing_required_steps_file) in str(result.exception)
    assert not isinstance(result.exception, FileNotFoundError)


def test_optimize_required_steps_file_non_numeric_line_raises(
        cli_invoker: CliInvoker, tmp_path: Path,
) -> None:
    output_dir: Path = tmp_path / "ws_with_curls"
    (output_dir / "curls").mkdir(parents=True)
    (output_dir / "curls" / "req_0000.curl.sh").touch()
    required_steps_file: Path = tmp_path / "required.txt"
    required_steps_file.write_text("abc\n", encoding="utf-8")

    result: CliInvocationResult = cli_invoker.invoke([
        "optimize", "--output", str(output_dir), "--to", "0",
        "--success-criteria", '[{"type":"status_code","expected":200}]',
        "--required-steps-file", str(required_steps_file),
    ])

    assert isinstance(result.exception, ValueError)
    assert str(required_steps_file) in str(result.exception)


@pytest.mark.slow
def test_optimize_required_steps_file_keeps_index_that_would_otherwise_be_removed(
        cli_invoker: CliInvoker, main_workspace: Path, tmp_path: Path,
) -> None:
    scenario: ReplayScenario = ReplayScenario(cli_invoker, main_workspace, tmp_path)
    required_steps_file: Path = tmp_path / "required.txt"
    required_steps_file.write_text("5\n", encoding="utf-8")

    result: CliInvocationResult = cli_invoker.invoke([
        "optimize", "--output", str(scenario.workspace), "--to", "9",
        "--success-criteria", '[{"type":"status_code","expected":200}]',
        "--required-steps-file", str(required_steps_file),
    ])

    assert result.exception is None
    assert "Optimization SUCCESSFUL" in result.stdout
    steps_files: List[Path] = list((scenario.workspace / "replays").glob("optimized_*.txt"))
    assert len(steps_files) == 1
    assert steps_files[0].read_text(encoding="utf-8").splitlines() == ["0", "5", "9"]


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
