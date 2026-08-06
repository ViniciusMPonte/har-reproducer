from pathlib import Path

from tests.support.cli_invocation_result import CliInvocationResult
from tests.support.cli_invoker import CliInvoker
from tests.support.golden_workspace_factory import GoldenWorkspaceFactory


def test_parse_default(
        cli_invoker: CliInvoker,
        synthetic_flow_har: Path,
        golden_workspace_factory: GoldenWorkspaceFactory,
        golden_dir: Path,
        tmp_path: Path,
) -> None:
    output_dir: Path = tmp_path / "out"
    argv: list[str] = ["parse", "--har", str(synthetic_flow_har), "--output", str(output_dir)]
    golden: Path = golden_dir / "parse_default"

    first_result: CliInvocationResult = cli_invoker.invoke(argv)
    assert first_result.exception is None
    assert "Parsed HAR into 10 steps." in first_result.stdout
    output_dir.joinpath("stdout.txt").write_text(first_result.stdout, encoding="utf-8")
    golden_workspace_factory.create(output_dir).assert_matches(golden)

    second_result: CliInvocationResult = cli_invoker.invoke(argv)
    output_dir.joinpath("stdout.txt").write_text(second_result.stdout, encoding="utf-8")
    golden_workspace_factory.create(output_dir).assert_matches(golden)


def test_parse_default_output_omitted(
        cli_invoker: CliInvoker,
        synthetic_flow_har: Path,
        golden_workspace_factory: GoldenWorkspaceFactory,
        golden_dir: Path,
        tmp_path: Path,
) -> None:
    argv: list[str] = ["parse", "--har", str(synthetic_flow_har)]
    output_dir: Path = tmp_path / "output"

    result: CliInvocationResult = cli_invoker.invoke(argv)
    assert result.exception is None
    assert (output_dir / "parse" / "req_0000.json").exists()
    output_dir.joinpath("stdout.txt").write_text(result.stdout, encoding="utf-8")

    golden_workspace_factory.create(output_dir).assert_matches(golden_dir / "parse_default_output_omitted")


def test_parse_reset_removes_litter(
        cli_invoker: CliInvoker,
        synthetic_flow_har: Path,
        golden_workspace_factory: GoldenWorkspaceFactory,
        golden_dir: Path,
        tmp_path: Path,
) -> None:
    output_dir: Path = tmp_path / "out"
    output_dir.mkdir(parents=True)
    output_dir.joinpath("lixo.txt").write_text("lixo", encoding="utf-8")
    argv: list[str] = ["parse", "--har", str(synthetic_flow_har), "--output", str(output_dir), "--reset"]

    result: CliInvocationResult = cli_invoker.invoke(argv)
    assert result.exception is None
    assert not (output_dir / "lixo.txt").exists()
    output_dir.joinpath("stdout.txt").write_text(result.stdout, encoding="utf-8")

    golden_workspace_factory.create(output_dir).assert_matches(golden_dir / "parse_reset_removes_litter")


def test_parse_without_reset_preserves_litter(
        cli_invoker: CliInvoker,
        synthetic_flow_har: Path,
        golden_workspace_factory: GoldenWorkspaceFactory,
        golden_dir: Path,
        tmp_path: Path,
) -> None:
    output_dir: Path = tmp_path / "out"
    output_dir.mkdir(parents=True)
    output_dir.joinpath("lixo.txt").write_text("lixo", encoding="utf-8")
    argv: list[str] = ["parse", "--har", str(synthetic_flow_har), "--output", str(output_dir)]

    result: CliInvocationResult = cli_invoker.invoke(argv)
    assert result.exception is None
    assert (output_dir / "lixo.txt").exists()
    output_dir.joinpath("stdout.txt").write_text(result.stdout, encoding="utf-8")

    golden_workspace_factory.create(output_dir).assert_matches(golden_dir / "parse_without_reset_preserves_litter")
