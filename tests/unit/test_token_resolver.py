from pathlib import Path

from har_reproducer.models import AgentType, Extractor
from har_reproducer.session import SessionStore
from har_reproducer.tracking.token_resolver import TokenResolver
from tests.support.fake_extractor_runner import FakeExtractorRunner


def test_resolve_all_skips_unverified_extractor(tmp_path: Path) -> None:
    session_store: SessionStore = SessionStore()
    session_store.state.registry["t1"] = Extractor(
        token_id="t1", code="def f(r): pass", agent_type=AgentType.REGEX, verified=False, origin_step=2
    )
    extractor_runner: FakeExtractorRunner = FakeExtractorRunner(run_result="valor")
    resolver: TokenResolver = TokenResolver(tmp_path, session_store, extractor_runner)

    resolver.resolve_all()

    assert extractor_runner.run_calls == []


def test_refresh_token_skips_when_response_file_missing(tmp_path: Path) -> None:
    session_store: SessionStore = SessionStore()
    session_store.state.registry["t1"] = Extractor(
        token_id="t1", code="def f(r): pass", agent_type=AgentType.REGEX, verified=True, origin_step=2
    )
    extractor_runner: FakeExtractorRunner = FakeExtractorRunner(run_result="valor")
    resolver: TokenResolver = TokenResolver(tmp_path, session_store, extractor_runner)

    resolver.resolve_all()

    assert extractor_runner.run_calls == []


def test_resolve_all_sets_token_when_response_exists_and_run_succeeds(tmp_path: Path) -> None:
    (tmp_path / "res_0002.json").write_text("{}", encoding="utf-8")
    session_store: SessionStore = SessionStore()
    session_store.state.registry["t1"] = Extractor(
        token_id="t1", code="def f(r): pass", agent_type=AgentType.REGEX, verified=True, origin_step=2
    )
    extractor_runner: FakeExtractorRunner = FakeExtractorRunner(run_result="novo-valor")
    resolver: TokenResolver = TokenResolver(tmp_path, session_store, extractor_runner)

    resolver.resolve_all()

    assert session_store.get_token("t1") == "novo-valor"


def test_resolve_all_does_not_propagate_extractor_runner_exception(tmp_path: Path) -> None:
    (tmp_path / "res_0002.json").write_text("{}", encoding="utf-8")
    session_store: SessionStore = SessionStore()
    session_store.state.registry["t1"] = Extractor(
        token_id="t1", code="def f(r): pass", agent_type=AgentType.REGEX, verified=True, origin_step=2
    )
    extractor_runner: FakeExtractorRunner = FakeExtractorRunner(run_result=RuntimeError("boom"))
    resolver: TokenResolver = TokenResolver(tmp_path, session_store, extractor_runner)

    resolver.resolve_all()


def test_resolve_all_without_force_skips_already_resolved_token(tmp_path: Path) -> None:
    (tmp_path / "res_0002.json").write_text("{}", encoding="utf-8")
    session_store: SessionStore = SessionStore()
    session_store.set_token("t1", "ja-resolvido")
    session_store.state.registry["t1"] = Extractor(
        token_id="t1", code="def f(r): pass", agent_type=AgentType.REGEX, verified=True, origin_step=2
    )
    extractor_runner: FakeExtractorRunner = FakeExtractorRunner(run_result="novo-valor")
    resolver: TokenResolver = TokenResolver(tmp_path, session_store, extractor_runner)

    resolver.resolve_all(force=False)
    assert extractor_runner.run_calls == []

    resolver.resolve_all(force=True)
    assert len(extractor_runner.run_calls) == 1
