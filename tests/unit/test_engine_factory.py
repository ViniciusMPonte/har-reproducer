from pathlib import Path

from har_reproducer.engines.construction.engine_factory import EngineFactory
from har_reproducer.engines.construction.engine_mode import EngineMode
from har_reproducer.engines.dry_engine import DryEngine
from har_reproducer.engines.engine import Engine
from har_reproducer.fs_io.workspace import Workspace
from har_reproducer.models import ProjectConfig
from tests.support.fake_script_executor import FakeScriptExecutor
from tests.support.fake_sleeper import FakeSleeper
from tests.support.stub_http_transport import StubHttpTransport


def _factory(tmp_path: Path) -> EngineFactory:
    return EngineFactory(Workspace(tmp_path), ProjectConfig(), FakeScriptExecutor([]), FakeSleeper())


def test_resolve_class_maps_modes_to_engine_classes(tmp_path: Path) -> None:
    factory: EngineFactory = _factory(tmp_path)

    assert factory.resolve_class(EngineMode.MAIN) is Engine
    assert factory.resolve_class(EngineMode.DRY) is DryEngine


def test_create_dry_ignores_http_transport(tmp_path: Path) -> None:
    factory: EngineFactory = _factory(tmp_path)

    engine: Engine = factory.create(EngineMode.DRY, Path("flow.har"), http_transport=StubHttpTransport(None))

    assert engine.http_transport is None


def test_create_dry_uses_original_responses_directory(tmp_path: Path) -> None:
    factory: EngineFactory = _factory(tmp_path)
    workspace: Workspace = factory.workspace

    engine: Engine = factory.create(EngineMode.DRY, Path("flow.har"))

    assert engine.token_resolver.responses_dir == workspace.original_responses
    assert engine.tracker.candidate_resolver.responses_dir == workspace.original_responses


def test_create_main_passes_through_transport_and_uses_real_responses_directory(tmp_path: Path) -> None:
    factory: EngineFactory = _factory(tmp_path)
    workspace: Workspace = factory.workspace
    transport: StubHttpTransport = StubHttpTransport(None)

    engine: Engine = factory.create(EngineMode.MAIN, Path("flow.har"), http_transport=transport)

    assert engine.http_transport is transport
    assert engine.token_resolver.responses_dir == workspace.real_responses


def test_llm_is_none_when_project_config_has_no_llm_settings(tmp_path: Path) -> None:
    factory: EngineFactory = _factory(tmp_path)

    assert factory.llm is None
