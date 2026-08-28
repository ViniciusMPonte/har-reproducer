from pathlib import Path

from har_reproducer.engines.construction.engine_factory import EngineFactory
from har_reproducer.engines.construction.engine_mode import EngineMode
from har_reproducer.engines.dry_engine import DryEngine
from har_reproducer.engines.engine import Engine
from har_reproducer.fs_io.workspace import Workspace
from har_reproducer.models import ProjectConfig
from har_reproducer.replay.replay_result_comparator import ReplayResultComparator
from har_reproducer.reproduction.cookie_jar_curl_override import CookieJarCurlOverride
from har_reproducer.session.cookie_jar import CookieJar
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
    assert engine.tracker.candidate_resolver.discovery_corpus.responses_dir == workspace.original_responses
    assert engine.tracker.candidate_resolver.execution_corpus is None


def test_create_main_passes_through_transport_and_uses_real_responses_directory(tmp_path: Path) -> None:
    factory: EngineFactory = _factory(tmp_path)
    workspace: Workspace = factory.workspace
    transport: StubHttpTransport = StubHttpTransport(None)

    engine: Engine = factory.create(EngineMode.MAIN, Path("flow.har"), http_transport=transport)

    assert engine.http_transport is transport
    assert engine.token_resolver.responses_dir == workspace.real_responses
    assert engine.tracker.candidate_resolver.discovery_corpus.responses_dir == workspace.original_responses
    assert engine.tracker.candidate_resolver.execution_corpus.responses_dir == workspace.real_responses


def test_llm_is_none_when_project_config_has_no_llm_settings(tmp_path: Path) -> None:
    factory: EngineFactory = _factory(tmp_path)

    assert factory.llm is None


def test_create_main_injects_comparator_bound_to_workspace(tmp_path: Path) -> None:
    factory: EngineFactory = _factory(tmp_path)

    engine: Engine = factory.create(EngineMode.MAIN, Path("flow.har"), http_transport=StubHttpTransport(None))

    assert isinstance(engine.comparator, ReplayResultComparator)
    assert engine.comparator.workspace is factory.workspace


def test_create_dry_injects_comparator_bound_to_workspace(tmp_path: Path) -> None:
    factory: EngineFactory = _factory(tmp_path)

    engine: Engine = factory.create(EngineMode.DRY, Path("flow.har"))

    assert isinstance(engine.comparator, ReplayResultComparator)
    assert engine.comparator.workspace is factory.workspace


def test_create_main_injects_cookie_jar_and_matching_curl_override(tmp_path: Path) -> None:
    factory: EngineFactory = _factory(tmp_path)

    engine: Engine = factory.create(EngineMode.MAIN, Path("flow.har"), http_transport=StubHttpTransport(None))

    assert isinstance(engine.cookie_jar, CookieJar)
    assert isinstance(engine.cookie_jar_curl_override, CookieJarCurlOverride)
    assert engine.cookie_jar_curl_override.cookie_jar is engine.cookie_jar


def test_create_dry_injects_cookie_jar_and_matching_curl_override(tmp_path: Path) -> None:
    factory: EngineFactory = _factory(tmp_path)

    engine: Engine = factory.create(EngineMode.DRY, Path("flow.har"))

    assert isinstance(engine.cookie_jar, CookieJar)
    assert isinstance(engine.cookie_jar_curl_override, CookieJarCurlOverride)
    assert engine.cookie_jar_curl_override.cookie_jar is engine.cookie_jar
