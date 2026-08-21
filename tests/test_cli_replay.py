import json
import shutil
from pathlib import Path
from typing import Iterator

import pytest

from har_reproducer.replay.curl_token_comment import ReplayStatusPhrase

from tests.support.canned_http_server import CannedHttpServer
from tests.support.cli_invocation_result import CliInvocationResult
from tests.support.cli_invoker import CliInvoker
from tests.support.golden_workspace_factory import GoldenWorkspaceFactory
from tests.support.har_materializer import HarMaterializer
from tests.support.replay_scenario import ReplayScenario
from tests.support.token_failure_guard import TokenFailureGuard


@pytest.fixture(scope="session")
def canned_http_server() -> Iterator[CannedHttpServer]:
    server: CannedHttpServer = CannedHttpServer(CannedHttpServer.free_port())
    server.start()
    yield server
    server.stop()


@pytest.fixture(scope="session")
def network_session_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("network_session")


@pytest.fixture(scope="session")
def main_workspace(canned_http_server: CannedHttpServer, network_session_dir: Path) -> Path:
    har_source: Path = Path(__file__).parent / "fixtures" / "synthetic_flow.har"
    har_path: Path = HarMaterializer().materialize(
        har_source, network_session_dir / "synthetic_flow.har", canned_http_server.port,
    )
    proxy_port: int = CannedHttpServer.free_port()
    config_path: Path = network_session_dir / "main_config.json"
    config_path.write_text(json.dumps({"proxy_port": proxy_port}), encoding="utf-8")
    output_dir: Path = network_session_dir / "main_ws"

    result: CliInvocationResult = CliInvoker().invoke(
        ["run", "--har", str(har_path), "--mode", "main", "--output", str(output_dir), "--config", str(config_path)]
    )
    if result.exception is not None:
        raise RuntimeError(f"run --mode main falhou: {result.exception!r}\n{result.stdout}\n{result.stderr}")
    output_dir.joinpath("stdout.txt").write_text(result.stdout, encoding="utf-8")
    return output_dir


@pytest.fixture(scope="session")
def main_workspace_golden_factory(network_session_dir: Path) -> GoldenWorkspaceFactory:
    return GoldenWorkspaceFactory(network_session_dir)


@pytest.fixture(scope="session")
def dry_workspace_network(canned_http_server: CannedHttpServer, network_session_dir: Path) -> Path:
    har_source: Path = Path(__file__).parent / "fixtures" / "synthetic_flow.har"
    har_path: Path = HarMaterializer().materialize(
        har_source, network_session_dir / "synthetic_flow_dry.har", canned_http_server.port,
    )
    output_dir: Path = network_session_dir / "dry_ws"

    result: CliInvocationResult = CliInvoker().invoke(
        ["run", "--har", str(har_path), "--mode", "dry", "--output", str(output_dir)]
    )
    if result.exception is not None:
        raise RuntimeError(f"run --mode dry falhou: {result.exception!r}\n{result.stdout}\n{result.stderr}")
    return output_dir


@pytest.mark.slow
def test_run_main(
        main_workspace: Path,
        main_workspace_golden_factory: GoldenWorkspaceFactory,
        golden_dir: Path,
) -> None:
    stdout: str = main_workspace.joinpath("stdout.txt").read_text(encoding="utf-8")
    assert stdout.count("Attempt 1 failed") == 0
    assert stdout.rstrip().endswith("Reproduction SUCCESSFUL: Target state reached.")
    TokenFailureGuard().assert_at_most_one_failure_per_step(stdout)

    main_workspace_golden_factory.create(main_workspace).assert_matches(golden_dir / "run_main")


@pytest.mark.slow
def test_replay_all(
        cli_invoker: CliInvoker,
        main_workspace: Path,
        golden_workspace_factory: GoldenWorkspaceFactory,
        golden_dir: Path,
        tmp_path: Path,
) -> None:
    scenario: ReplayScenario = ReplayScenario(cli_invoker, main_workspace, tmp_path)
    result: CliInvocationResult = scenario.run(["--mode", "all"])

    assert result.exception is None
    assert "Replay Validation Result: ✓ SUCCESS" in result.stdout
    assert scenario.executed_steps(result.stdout) == [0, 3, 4, 5, 6, 7, 8, 9]
    assert len(scenario.replay_run_dirs()) == 1
    TokenFailureGuard().assert_at_most_one_failure_per_step(result.stdout)
    scenario.workspace.joinpath("stdout.txt").write_text(result.stdout, encoding="utf-8")

    golden_workspace_factory.create(scenario.workspace).assert_matches(golden_dir / "replay_all")


@pytest.mark.slow
def test_replay_slice_full(
        cli_invoker: CliInvoker,
        main_workspace: Path,
        golden_workspace_factory: GoldenWorkspaceFactory,
        golden_dir: Path,
        tmp_path: Path,
) -> None:
    scenario: ReplayScenario = ReplayScenario(cli_invoker, main_workspace, tmp_path)
    result: CliInvocationResult = scenario.run(["--mode", "slice"])

    assert result.exception is None
    assert "Replay Validation Result: ✓ SUCCESS" in result.stdout
    assert scenario.executed_steps(result.stdout) == [0, 3, 4, 5, 6, 7, 8, 9]
    assert len(scenario.replay_run_dirs()) == 1
    TokenFailureGuard().assert_at_most_one_failure_per_step(result.stdout)
    scenario.workspace.joinpath("stdout.txt").write_text(result.stdout, encoding="utf-8")

    golden_workspace_factory.create(scenario.workspace).assert_matches(golden_dir / "replay_slice_full")


@pytest.mark.slow
def test_replay_slice_0_3(
        cli_invoker: CliInvoker,
        main_workspace: Path,
        golden_workspace_factory: GoldenWorkspaceFactory,
        golden_dir: Path,
        tmp_path: Path,
) -> None:
    scenario: ReplayScenario = ReplayScenario(cli_invoker, main_workspace, tmp_path)
    result: CliInvocationResult = scenario.run(["--mode", "slice", "--from", "0", "--to", "3"])

    assert result.exception is None
    assert "Replay Validation Result: ✓ SUCCESS" in result.stdout
    assert scenario.executed_steps(result.stdout) == [0, 3]
    assert len(scenario.replay_run_dirs()) == 1
    TokenFailureGuard().assert_at_most_one_failure_per_step(result.stdout)
    scenario.workspace.joinpath("stdout.txt").write_text(result.stdout, encoding="utf-8")

    golden_workspace_factory.create(scenario.workspace).assert_matches(golden_dir / "replay_slice_0_3")


@pytest.mark.slow
def test_replay_smart_noflag(
        cli_invoker: CliInvoker,
        main_workspace: Path,
        golden_workspace_factory: GoldenWorkspaceFactory,
        golden_dir: Path,
        tmp_path: Path,
) -> None:
    scenario: ReplayScenario = ReplayScenario(cli_invoker, main_workspace, tmp_path)
    result: CliInvocationResult = scenario.run(["--mode", "smart"])

    assert result.exception is None
    assert "Replay Validation Result: ✓ SUCCESS" in result.stdout
    assert scenario.executed_steps(result.stdout) == [0, 3, 9]
    assert len(scenario.replay_run_dirs()) == 1
    TokenFailureGuard().assert_at_most_one_failure_per_step(result.stdout)
    scenario.workspace.joinpath("stdout.txt").write_text(result.stdout, encoding="utf-8")

    golden_workspace_factory.create(scenario.workspace).assert_matches(golden_dir / "replay_smart_noflag")


@pytest.mark.slow
def test_replay_smart_to_4(
        cli_invoker: CliInvoker,
        main_workspace: Path,
        golden_workspace_factory: GoldenWorkspaceFactory,
        golden_dir: Path,
        tmp_path: Path,
) -> None:
    scenario: ReplayScenario = ReplayScenario(cli_invoker, main_workspace, tmp_path)
    result: CliInvocationResult = scenario.run(["--mode", "smart", "--to", "4"])

    assert result.exception is None
    assert "Replay Validation Result: ✓ SUCCESS" in result.stdout
    assert scenario.executed_steps(result.stdout) == [0, 3, 4]
    assert len(scenario.replay_run_dirs()) == 1
    TokenFailureGuard().assert_at_most_one_failure_per_step(result.stdout)
    scenario.workspace.joinpath("stdout.txt").write_text(result.stdout, encoding="utf-8")

    golden_workspace_factory.create(scenario.workspace).assert_matches(golden_dir / "replay_smart_to_4")


@pytest.mark.slow
def test_replay_smart_from_3(
        cli_invoker: CliInvoker,
        main_workspace: Path,
        golden_workspace_factory: GoldenWorkspaceFactory,
        golden_dir: Path,
        tmp_path: Path,
) -> None:
    scenario: ReplayScenario = ReplayScenario(cli_invoker, main_workspace, tmp_path)
    result: CliInvocationResult = scenario.run(["--mode", "smart", "--from", "3", "--to", "4"])

    assert result.exception is None
    assert "Replay Validation Result: ✓ SUCCESS" in result.stdout
    assert scenario.executed_steps(result.stdout) == [3, 4]
    assert len(scenario.replay_run_dirs()) == 1
    TokenFailureGuard().assert_at_most_one_failure_per_step(result.stdout)
    scenario.workspace.joinpath("stdout.txt").write_text(result.stdout, encoding="utf-8")

    golden_workspace_factory.create(scenario.workspace).assert_matches(golden_dir / "replay_smart_from_3")


@pytest.mark.slow
def test_replay_smart_to_6(
        cli_invoker: CliInvoker,
        main_workspace: Path,
        golden_workspace_factory: GoldenWorkspaceFactory,
        golden_dir: Path,
        tmp_path: Path,
) -> None:
    scenario: ReplayScenario = ReplayScenario(cli_invoker, main_workspace, tmp_path)
    result: CliInvocationResult = scenario.run(["--mode", "smart", "--to", "6"])

    assert result.exception is None
    assert "Replay Validation Result: ✓ SUCCESS" in result.stdout
    assert scenario.executed_steps(result.stdout) == [6]
    assert len(scenario.replay_run_dirs()) == 1
    assert "could not be dynamically resolved during replay" not in result.stdout
    TokenFailureGuard().assert_at_most_one_failure_per_step(result.stdout)
    scenario.workspace.joinpath("stdout.txt").write_text(result.stdout, encoding="utf-8")

    golden_workspace_factory.create(scenario.workspace).assert_matches(golden_dir / "replay_smart_to_6")


@pytest.mark.slow
def test_replay_list_asc(
        cli_invoker: CliInvoker,
        main_workspace: Path,
        golden_workspace_factory: GoldenWorkspaceFactory,
        golden_dir: Path,
        tmp_path: Path,
) -> None:
    scenario: ReplayScenario = ReplayScenario(cli_invoker, main_workspace, tmp_path)
    steps_file: Path = tmp_path / "steps.txt"
    steps_file.write_text("0\n3\n4\n", encoding="utf-8")
    result: CliInvocationResult = scenario.run(["--mode", "list", "--steps-file", str(steps_file)])

    assert result.exception is None
    assert "Replay Validation Result: ✓ SUCCESS" in result.stdout
    assert scenario.executed_steps(result.stdout) == [0, 3, 4]
    assert len(scenario.replay_run_dirs()) == 1
    TokenFailureGuard().assert_at_most_one_failure_per_step(result.stdout)
    scenario.workspace.joinpath("stdout.txt").write_text(result.stdout, encoding="utf-8")

    golden_workspace_factory.create(scenario.workspace).assert_matches(golden_dir / "replay_list_asc")


@pytest.mark.slow
def test_replay_list_out_of_order(
        cli_invoker: CliInvoker,
        main_workspace: Path,
        golden_workspace_factory: GoldenWorkspaceFactory,
        golden_dir: Path,
        tmp_path: Path,
) -> None:
    scenario: ReplayScenario = ReplayScenario(cli_invoker, main_workspace, tmp_path)
    steps_file: Path = tmp_path / "steps.txt"
    steps_file.write_text("4\n3\n", encoding="utf-8")
    result: CliInvocationResult = scenario.run(["--mode", "list", "--steps-file", str(steps_file)])

    assert result.exception is None
    assert "could not be dynamically resolved during replay; using captured value instead." in result.stdout
    assert "curl: (3) nested brace" not in result.stdout
    assert "Step 4 completed with status 0" not in result.stdout
    assert "Step 4 completed with status 200" in result.stdout
    assert "Replay step results:" in result.stdout
    assert "Replay Validation Result: ✓ SUCCESS (step 3 status code vs. original)" in result.stdout
    assert "Reproduction SUCCESSFUL" in result.stdout
    assert scenario.executed_steps(result.stdout) == [4, 3]
    assert len(scenario.replay_run_dirs()) == 1
    TokenFailureGuard().assert_at_most_one_failure_per_step(result.stdout)
    curl_step4: str = scenario.workspace.joinpath("curls", "req_0004.curl.sh").read_text(encoding="utf-8")
    assert "# [Token ade6a53080262635799eb7ec66e824e8 comes from response of step " in curl_step4
    assert ReplayStatusPhrase.COULD_NOT_EXTRACT.value in curl_step4
    scenario.workspace.joinpath("stdout.txt").write_text(result.stdout, encoding="utf-8")

    golden_workspace_factory.create(scenario.workspace).assert_matches(golden_dir / "replay_list_out_of_order")


@pytest.mark.slow
def test_replay_ref_fallback(
        cli_invoker: CliInvoker,
        main_workspace: Path,
        golden_workspace_factory: GoldenWorkspaceFactory,
        golden_dir: Path,
        tmp_path: Path,
) -> None:
    scenario: ReplayScenario = ReplayScenario(cli_invoker, main_workspace, tmp_path)
    reference_dir: Path = tmp_path / "reference"
    shutil.copytree(scenario.workspace / "real_responses", reference_dir)
    reference_dir.joinpath("res_0003.json").unlink()
    config_path: Path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"response_reference_dir": str(reference_dir)}), encoding="utf-8")
    steps_file: Path = tmp_path / "steps.txt"
    steps_file.write_text("4\n", encoding="utf-8")

    result: CliInvocationResult = scenario.run(["--mode", "list", "--steps-file", str(steps_file)], config_path)

    assert result.exception is None
    assert "Replay Validation Result: ✓ SUCCESS" in result.stdout
    assert "Failed to resolve" not in result.stdout
    assert scenario.executed_steps(result.stdout) == [4]
    assert len(scenario.replay_run_dirs()) == 1
    TokenFailureGuard().assert_at_most_one_failure_per_step(result.stdout)
    scenario.workspace.joinpath("stdout.txt").write_text(result.stdout, encoding="utf-8")

    golden_workspace_factory.create(scenario.workspace).assert_matches(golden_dir / "replay_ref_fallback")


@pytest.mark.slow
def test_replay_dry_ref_fallback(
        cli_invoker: CliInvoker,
        dry_workspace_network: Path,
        golden_workspace_factory: GoldenWorkspaceFactory,
        golden_dir: Path,
        tmp_path: Path,
) -> None:
    scenario: ReplayScenario = ReplayScenario(cli_invoker, dry_workspace_network, tmp_path)
    steps_file: Path = tmp_path / "steps.txt"
    steps_file.write_text("4\n", encoding="utf-8")
    result: CliInvocationResult = scenario.run(["--mode", "list", "--steps-file", str(steps_file)])

    assert result.exception is None
    assert "Failed to resolve" not in result.stdout
    assert "using captured value" not in result.stdout
    assert "Step 4 completed with status 200" in result.stdout
    assert "Replay Validation Result: ✓ SUCCESS" in result.stdout
    assert scenario.executed_steps(result.stdout) == [4]
    assert len(scenario.replay_run_dirs()) == 1
    TokenFailureGuard().assert_at_most_one_failure_per_step(result.stdout)
    scenario.workspace.joinpath("stdout.txt").write_text(result.stdout, encoding="utf-8")

    golden_workspace_factory.create(scenario.workspace).assert_matches(golden_dir / "replay_dry_ref_fallback")


@pytest.mark.slow
def test_replay_missing_step(
        cli_invoker: CliInvoker,
        main_workspace: Path,
        tmp_path: Path,
) -> None:
    scenario: ReplayScenario = ReplayScenario(cli_invoker, main_workspace, tmp_path)
    steps_file: Path = tmp_path / "steps.txt"
    steps_file.write_text("0\n1\n", encoding="utf-8")

    result: CliInvocationResult = scenario.run(["--mode", "list", "--steps-file", str(steps_file)])

    assert isinstance(result.exception, ValueError)
    assert "step(s) [1] não existem no workspace" in str(result.exception)
    TokenFailureGuard().assert_at_most_one_failure_per_step(result.stdout)
