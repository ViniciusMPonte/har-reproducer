from pathlib import Path
from typing import List

import pytest

from tests.support.cli_invoker import CliInvoker
from tests.support.golden_workspace_factory import GoldenWorkspaceFactory
from tests.support.har_materializer import HarMaterializer

FIXTURES_DIR: Path = Path(__file__).parent / "fixtures"
GOLDEN_DIR: Path = Path(__file__).parent / "golden"
OFFLINE_PORT: int = 19999


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
    return GOLDEN_DIR


@pytest.fixture
def synthetic_flow_har(tmp_path: Path) -> Path:
    source: Path = FIXTURES_DIR / "synthetic_flow.har"
    destination: Path = tmp_path / "synthetic_flow.har"
    return HarMaterializer().materialize(source, destination, OFFLINE_PORT)


@pytest.fixture
def minimal_flow_har(tmp_path: Path) -> Path:
    source: Path = FIXTURES_DIR / "minimal_flow.har"
    destination: Path = tmp_path / "minimal_flow.har"
    return HarMaterializer().materialize(source, destination, OFFLINE_PORT)


@pytest.fixture
def cli_invoker() -> CliInvoker:
    return CliInvoker()


@pytest.fixture
def golden_workspace_factory(tmp_path: Path) -> GoldenWorkspaceFactory:
    return GoldenWorkspaceFactory(tmp_path)
