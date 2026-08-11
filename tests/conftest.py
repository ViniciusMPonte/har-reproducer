from pathlib import Path
from typing import ClassVar, List

import pytest

from tests.support.cli_invoker import CliInvoker
from tests.support.golden_workspace_factory import GoldenWorkspaceFactory
from tests.support.har_materializer import HarMaterializer


class OfflineFixtureConfig:
    FIXTURES_DIR: ClassVar[Path] = Path(__file__).parent / "fixtures"
    GOLDEN_DIR: ClassVar[Path] = Path(__file__).parent / "golden"
    OFFLINE_PORT: ClassVar[int] = 19999


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--runslow",
        action="store_true",
        default=False,
        help="executa também os cenários de rede (slow)",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "slow: cenário de rede, fora da rodada padrão")


def pytest_collection_modifyitems(config: pytest.Config, items: List[pytest.Item]) -> None:
    if config.getoption("--runslow"):
        return
    skip_slow: pytest.MarkDecorator = pytest.mark.skip(reason="precisa de --runslow")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip_slow)


@pytest.fixture
def golden_dir() -> Path:
    return OfflineFixtureConfig.GOLDEN_DIR


@pytest.fixture
def synthetic_flow_har(tmp_path: Path) -> Path:
    source: Path = OfflineFixtureConfig.FIXTURES_DIR / "synthetic_flow.har"
    destination: Path = tmp_path / "synthetic_flow.har"
    return HarMaterializer().materialize(source, destination, OfflineFixtureConfig.OFFLINE_PORT)


@pytest.fixture
def minimal_flow_har(tmp_path: Path) -> Path:
    source: Path = OfflineFixtureConfig.FIXTURES_DIR / "minimal_flow.har"
    destination: Path = tmp_path / "minimal_flow.har"
    return HarMaterializer().materialize(source, destination, OfflineFixtureConfig.OFFLINE_PORT)


@pytest.fixture
def cli_invoker() -> CliInvoker:
    return CliInvoker()


@pytest.fixture
def dry_workspace(cli_invoker: CliInvoker, synthetic_flow_har: Path, tmp_path: Path) -> Path:
    output_dir: Path = tmp_path / "dry_ws"
    result = cli_invoker.invoke(
        ["run", "--har", str(synthetic_flow_har), "--mode", "dry", "--output", str(output_dir)]
    )
    if result.exception is not None:
        raise RuntimeError(f"run --mode dry falhou: {result.exception!r}\n{result.stdout}\n{result.stderr}")
    return output_dir


@pytest.fixture
def golden_workspace_factory(tmp_path: Path) -> GoldenWorkspaceFactory:
    return GoldenWorkspaceFactory(tmp_path)
