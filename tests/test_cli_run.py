from pathlib import Path

from tests.support.cli_invocation_result import CliInvocationResult
from tests.support.cli_invoker import CliInvoker
from tests.support.golden_workspace_factory import GoldenWorkspaceFactory


def test_run_dry_default(
        cli_invoker: CliInvoker,
        synthetic_flow_har: Path,
        golden_workspace_factory: GoldenWorkspaceFactory,
        golden_dir: Path,
        tmp_path: Path,
) -> None:
    output_dir: Path = tmp_path / "out"
    argv: list[str] = ["run", "--har", str(synthetic_flow_har), "--mode", "dry", "--output", str(output_dir)]

    result: CliInvocationResult = cli_invoker.invoke(argv)
    assert result.exception is None
    assert result.stdout.index("Step 0 completed with status 200") < result.stdout.index(
        "Step 1 skipped (unsupported scheme 'wss')")
    assert result.stdout.index("Step 1 skipped (unsupported scheme 'wss')") < result.stdout.index(
        "Step 2 skipped (skippable method 'OPTIONS')")
    assert result.stdout.index("Step 2 skipped (skippable method 'OPTIONS')") < result.stdout.index(
        "Step 3 completed with status 200")
    assert "Attempt 1 failed" not in result.stdout
    assert result.stdout.index("Step 3 completed with status 200") < result.stdout.index(
        "[AVISO] Não foi possível determinar a origem do token 'PLAINVAL777...'.")
    output_dir.joinpath("stdout.txt").write_text(result.stdout, encoding="utf-8")

    golden_workspace_factory.create(output_dir).assert_matches(golden_dir / "run_dry_default")


def test_run_dry_reset_removes_litter(
        cli_invoker: CliInvoker,
        synthetic_flow_har: Path,
        golden_workspace_factory: GoldenWorkspaceFactory,
        golden_dir: Path,
        tmp_path: Path,
) -> None:
    output_dir: Path = tmp_path / "out"
    output_dir.mkdir(parents=True)
    output_dir.joinpath("lixo.txt").write_text("lixo", encoding="utf-8")
    argv: list[str] = ["run", "--har", str(synthetic_flow_har), "--mode", "dry", "--output", str(output_dir), "--reset"]

    result: CliInvocationResult = cli_invoker.invoke(argv)
    assert result.exception is None
    assert not (output_dir / "lixo.txt").exists()
    output_dir.joinpath("stdout.txt").write_text(result.stdout, encoding="utf-8")

    golden_workspace_factory.create(output_dir).assert_matches(golden_dir / "run_dry_reset_removes_litter")


def test_run_dry_skip_rules_methods(
        cli_invoker: CliInvoker,
        synthetic_flow_har: Path,
        golden_workspace_factory: GoldenWorkspaceFactory,
        golden_dir: Path,
        tmp_path: Path,
) -> None:
    output_dir: Path = tmp_path / "out"
    config_path: Path = tmp_path / "config.json"
    config_path.write_text('{"skip_rules": {"methods": ["OPTIONS", "POST"]}}', encoding="utf-8")
    argv: list[str] = [
        "run", "--har", str(synthetic_flow_har), "--mode", "dry",
        "--output", str(output_dir), "--config", str(config_path),
    ]

    result: CliInvocationResult = cli_invoker.invoke(argv)
    assert result.exception is None
    assert "Attempt" not in result.stdout
    assert "Step 3 skipped (skippable method 'POST')" in result.stdout
    assert "Step 9 skipped (skippable method 'POST')" in result.stdout
    output_dir.joinpath("stdout.txt").write_text(result.stdout, encoding="utf-8")

    extractor_meta_files: list[Path] = sorted((output_dir / "extractors").glob("*.meta.json"))
    assert len(extractor_meta_files) == 4

    original_response: str = (output_dir / "original_responses" / "res_0003.json").read_text(encoding="utf-8")
    assert '"status_code": 200' in original_response
    assert '{\\"id\\": 4242, \\"ok\\": true}' in original_response

    real_request: str = (output_dir / "real_requests" / "req_0003.json").read_text(encoding="utf-8")
    assert '"is_skippable": true' in real_request

    golden_workspace_factory.create(output_dir).assert_matches(golden_dir / "run_dry_skip_rules_methods")
