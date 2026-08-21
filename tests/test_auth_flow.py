from pathlib import Path
from typing import ClassVar, Iterator

import pytest

from tests.support.canned_http_server import CannedHttpServer
from tests.support.cli_invocation_result import CliInvocationResult
from tests.support.cli_invoker import CliInvoker
from tests.support.golden_workspace_factory import GoldenWorkspaceFactory
from tests.support.har_materializer import HarMaterializer


class AuthFlowFixtureConfig:
    FIXTURES_DIR: ClassVar[Path] = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def auth_canned_server() -> Iterator[CannedHttpServer]:
    server: CannedHttpServer = CannedHttpServer(CannedHttpServer.free_port())
    server.start()
    yield server
    server.stop()


@pytest.fixture(scope="module")
def auth_flow_session_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("auth_flow_session")


@pytest.fixture(scope="module")
def auth_flow_workspace(auth_canned_server: CannedHttpServer, auth_flow_session_dir: Path) -> Path:
    har_path: Path = HarMaterializer().materialize(
        AuthFlowFixtureConfig.FIXTURES_DIR / "auth_flow.har",
        auth_flow_session_dir / "auth_flow.har",
        auth_canned_server.port,
    )
    output_dir: Path = auth_flow_session_dir / "ws"

    result: CliInvocationResult = CliInvoker().invoke(
        ["run", "--har", str(har_path), "--mode", "main", "--output", str(output_dir)]
    )
    if result.exception is not None:
        raise RuntimeError(f"run --mode main falhou: {result.exception!r}\n{result.stdout}\n{result.stderr}")
    output_dir.joinpath("stdout.txt").write_text(result.stdout, encoding="utf-8")
    return output_dir


@pytest.fixture(scope="module")
def auth_flow_golden_factory(auth_flow_session_dir: Path) -> GoldenWorkspaceFactory:
    return GoldenWorkspaceFactory(auth_flow_session_dir)


@pytest.mark.slow
def test_run_main_extracts_the_bearer_token_from_the_login_response(
        auth_flow_workspace: Path,
        auth_flow_golden_factory: GoldenWorkspaceFactory,
        golden_dir: Path,
) -> None:
    curl_text: str = (auth_flow_workspace / "curls" / "req_0001.curl.sh").read_text(encoding="utf-8")

    assert "Authorization: Bearer {{extractor:" in curl_text
    assert "har-token-" not in curl_text

    auth_flow_golden_factory.create(auth_flow_workspace).assert_matches(golden_dir / "run_auth_flow")


@pytest.mark.slow
def test_replay_all_reaches_protected_with_the_live_token(
        auth_flow_workspace: Path, cli_invoker: CliInvoker,
) -> None:
    result: CliInvocationResult = cli_invoker.invoke(
        ["replay", "--output", str(auth_flow_workspace), "--mode", "all"]
    )

    assert result.exception is None
    assert "Replay Validation Result: ✓ SUCCESS" in result.stdout
