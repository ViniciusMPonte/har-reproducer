from pathlib import Path

from tests.support.cli_invocation_result import CliInvocationResult
from tests.support.cli_invoker import CliInvoker
from tests.support.golden_normalizer import GoldenNormalizer


def test_run_invalid_mode(cli_invoker: CliInvoker, tmp_path: Path) -> None:
    result: CliInvocationResult = cli_invoker.invoke(["run", "--mode", "inexistente", "--har", str(tmp_path / "x.har")])
    assert isinstance(result.exception, SystemExit)
    assert "invalid choice: 'inexistente'" in result.stderr


def test_run_missing_har(cli_invoker: CliInvoker) -> None:
    result: CliInvocationResult = cli_invoker.invoke(["run"])
    assert isinstance(result.exception, SystemExit)
    assert "the following arguments are required: --har" in result.stderr


def test_replay_missing_mode(cli_invoker: CliInvoker, tmp_path: Path) -> None:
    result: CliInvocationResult = cli_invoker.invoke(["replay", "--output", str(tmp_path)])
    assert isinstance(result.exception, SystemExit)
    assert "--mode" in result.stderr


def test_replay_all_rejects_from_to_steps_file(cli_invoker: CliInvoker, tmp_path: Path) -> None:
    result: CliInvocationResult = cli_invoker.invoke(
        ["replay", "--output", str(tmp_path), "--mode", "all", "--from", "0"])
    assert isinstance(result.exception, ValueError)
    assert str(result.exception) == "--from/--to/--steps-file não se aplicam a --mode all"


def test_replay_slice_rejects_steps_file(cli_invoker: CliInvoker, tmp_path: Path) -> None:
    result: CliInvocationResult = cli_invoker.invoke(
        ["replay", "--output", str(tmp_path), "--mode", "slice", "--steps-file", "x.txt"])
    assert isinstance(result.exception, ValueError)
    assert str(result.exception) == "--steps-file não se aplica a --mode slice"


def test_replay_smart_rejects_steps_file(cli_invoker: CliInvoker, tmp_path: Path) -> None:
    result: CliInvocationResult = cli_invoker.invoke(
        ["replay", "--output", str(tmp_path), "--mode", "smart", "--steps-file", "x.txt"])
    assert isinstance(result.exception, ValueError)
    assert str(result.exception) == "--steps-file não se aplica a --mode smart"


def test_replay_slice_rejects_from_greater_than_to(cli_invoker: CliInvoker, tmp_path: Path) -> None:
    result: CliInvocationResult = cli_invoker.invoke(
        ["replay", "--output", str(tmp_path), "--mode", "slice", "--from", "5", "--to", "2"])
    assert isinstance(result.exception, ValueError)
    assert str(result.exception) == "--from não pode ser maior que --to"


def test_replay_list_requires_steps_file(cli_invoker: CliInvoker, tmp_path: Path) -> None:
    result: CliInvocationResult = cli_invoker.invoke(["replay", "--output", str(tmp_path), "--mode", "list"])
    assert isinstance(result.exception, ValueError)
    assert str(result.exception) == "--mode list exige --steps-file"


def test_replay_list_rejects_from_to(cli_invoker: CliInvoker, tmp_path: Path) -> None:
    result: CliInvocationResult = cli_invoker.invoke(
        ["replay", "--output", str(tmp_path), "--mode", "list", "--steps-file", "x.txt", "--from", "0"])
    assert isinstance(result.exception, ValueError)
    assert str(result.exception) == "--from/--to não se aplicam a --mode list"


def test_replay_workspace_does_not_exist(cli_invoker: CliInvoker, tmp_path: Path) -> None:
    output_dir: Path = tmp_path / "does_not_exist"
    normalizer: GoldenNormalizer = GoldenNormalizer(Path("/never-matches-anything"), tmp_path)

    result: CliInvocationResult = cli_invoker.invoke(["replay", "--output", str(output_dir), "--mode", "all"])
    assert isinstance(result.exception, ValueError)
    assert normalizer.normalize(str(result.exception)) == "Workspace directory does not exist: <TMP>/does_not_exist"


def test_replay_workspace_has_no_curl_files(cli_invoker: CliInvoker, tmp_path: Path) -> None:
    output_dir: Path = tmp_path / "empty_ws"
    output_dir.mkdir()
    normalizer: GoldenNormalizer = GoldenNormalizer(Path("/never-matches-anything"), tmp_path)

    result: CliInvocationResult = cli_invoker.invoke(["replay", "--output", str(output_dir), "--mode", "all"])
    assert isinstance(result.exception, ValueError)
    assert normalizer.normalize(str(result.exception)) == "Workspace has no curl files: <TMP>/empty_ws"


def test_replay_response_reference_dir_does_not_exist(cli_invoker: CliInvoker, tmp_path: Path) -> None:
    output_dir: Path = tmp_path / "ws_with_curls"
    (output_dir / "curls").mkdir(parents=True)
    (output_dir / "curls" / "req_0000.curl.sh").touch()
    reference_dir: Path = tmp_path / "missing_reference"
    config_path: Path = tmp_path / "config.json"
    config_path.write_text(f'{{"response_reference_dir": "{reference_dir}"}}', encoding="utf-8")
    normalizer: GoldenNormalizer = GoldenNormalizer(Path("/never-matches-anything"), tmp_path)

    argv: list[str] = ["replay", "--output", str(output_dir), "--mode", "all", "--config", str(config_path)]
    result: CliInvocationResult = cli_invoker.invoke(argv)
    assert isinstance(result.exception, ValueError)
    assert normalizer.normalize(str(result.exception)) == "response_reference_dir does not exist: <TMP>/missing_reference"
