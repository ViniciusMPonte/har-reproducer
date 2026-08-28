import json
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional

import pytest

from har_reproducer.engines.dry_engine import DryEngine
from har_reproducer.engines.engine import Engine
from har_reproducer.fs_io.workspace import Workspace
from har_reproducer.models import (
    CookieAttributes, SkipRulesConfig, Step, StepAnalysis, StepRequest, StepResponse, SuccessCriterion,
)
from har_reproducer.replay.replay_result_comparator import ReplayResultComparator
from har_reproducer.reproduction.cookie_jar_curl_override import CookieJarCurlOverride
from har_reproducer.reproduction.step_retry_policy import StepRetryPolicy
from har_reproducer.reproduction.step_skip_evaluator import StepSkipEvaluator
from har_reproducer.session.cookie_jar import CookieJar
from har_reproducer.session.session_store import SessionStore
from har_reproducer.validation.validator import Validator
from tests.support.stub_http_transport import StubHttpTransport


class RecordedResolveAllCall(NamedTuple):
    force: bool


class FakeTokenResolver:

    def __init__(self) -> None:
        self.calls: List[RecordedResolveAllCall] = []

    def resolve_all(self, force: bool = False) -> None:
        self.calls.append(RecordedResolveAllCall(force))


def _engine(
        tmp_path: Path,
        token_resolver: FakeTokenResolver,
        success_criteria: List[SuccessCriterion],
        engine_cls: type = Engine,
        http_transport: object = None,
        cookie_jar: Optional[CookieJar] = None,
) -> Engine:
    jar: CookieJar = cookie_jar if cookie_jar is not None else CookieJar()
    return engine_cls(
        har_path=Path("flow.har"),
        workspace=Workspace(tmp_path),
        session_store=SessionStore(),
        tracker=None,
        token_resolver=token_resolver,
        skip_evaluator=StepSkipEvaluator(SkipRulesConfig()),
        retry_policy=StepRetryPolicy(),
        validator=Validator(),
        comparator=ReplayResultComparator(Workspace(tmp_path)),
        success_criteria=success_criteria,
        http_transport=http_transport,
        cookie_jar=jar,
        cookie_jar_curl_override=CookieJarCurlOverride(jar),
    )


def _write_original_response(tmp_path: Path, index: int, status_code: int) -> None:
    Workspace(tmp_path).original_response_file(index).write_text(
        StepResponse(status_code=status_code).model_dump_json(), encoding="utf-8"
    )


def test_handle_recovery_does_nothing_when_status_matches_reference(tmp_path: Path) -> None:
    _write_original_response(tmp_path, 5, status_code=403)
    token_resolver: FakeTokenResolver = FakeTokenResolver()
    engine: Engine = _engine(tmp_path, token_resolver, [])

    handled: bool = engine.handle_recovery(5, StepResponse(status_code=403))

    assert handled is False
    assert token_resolver.calls == []


def test_handle_recovery_forces_token_refresh_when_status_diverges_from_reference(tmp_path: Path) -> None:
    _write_original_response(tmp_path, 5, status_code=200)
    token_resolver: FakeTokenResolver = FakeTokenResolver()
    engine: Engine = _engine(tmp_path, token_resolver, [])

    handled: bool = engine.handle_recovery(5, StepResponse(status_code=401))

    assert handled is True
    assert token_resolver.calls == [RecordedResolveAllCall(True)]


def test_handle_recovery_forces_token_refresh_for_transport_failure_without_any_reference(tmp_path: Path) -> None:
    token_resolver: FakeTokenResolver = FakeTokenResolver()
    engine: Engine = _engine(tmp_path, token_resolver, [])

    handled: bool = engine.handle_recovery(5, StepResponse(status_code=0))

    assert handled is True


def test_skip_entry_persists_skipped_response(tmp_path: Path) -> None:
    engine: Engine = _engine(tmp_path, FakeTokenResolver(), [])

    response: StepResponse = engine._skip_entry(3, "unsupported scheme 'ftp'")

    assert response.status_code == 0
    assert response.skipped is True
    assert response.skip_reason == "unsupported scheme 'ftp'"
    assert engine.workspace.response_file(3).exists()


def test_validate_final_true_when_no_success_criteria(tmp_path: Path) -> None:
    engine: Engine = _engine(tmp_path, FakeTokenResolver(), [])

    assert engine._validate_final(None) is True
    assert engine._validate_final(StepResponse(status_code=200)) is True


def test_dry_engine_execute_step_returns_har_response_without_transport(tmp_path: Path) -> None:
    engine: DryEngine = _engine(tmp_path, FakeTokenResolver(), [], engine_cls=DryEngine)
    step: Step = Step(
        index=0, request=StepRequest(url="https://x", method="GET"), response=StepResponse(status_code=200)
    )

    response: StepResponse = engine.execute_step(step)

    assert response.status_code == 200


def test_dry_engine_persist_response_step_is_a_no_op(tmp_path: Path) -> None:
    engine: DryEngine = _engine(tmp_path, FakeTokenResolver(), [], engine_cls=DryEngine)

    engine._persist_response_step(0, StepResponse(status_code=200))

    assert not engine.workspace.response_file(0).exists()


def _har_with_bodyless_entries(tmp_path: Path, bodyless: int, total: int) -> Path:
    entries: List[Dict[str, Any]] = []
    for index in range(total):
        content: Dict[str, Any] = {} if index < bodyless else {"text": "corpo", "mimeType": "text/plain"}
        entries.append({
            "request": {"url": "https://x", "method": "GET", "headers": [], "cookies": []},
            "response": {"status": 200, "headers": [], "cookies": [], "content": content},
        })
    har_path: Path = tmp_path / "flow.har"
    har_path.write_text(json.dumps({"log": {"entries": entries}}), encoding="utf-8")
    return har_path


class SilentEngine(DryEngine):

    def _process_entry(self, index: int, entry: Dict[str, Any], first_entry: Step) -> StepResponse:
        return StepResponse(status_code=200)


def _silent_engine(tmp_path: Path, har_path: Path) -> SilentEngine:
    engine: SilentEngine = _engine(tmp_path, FakeTokenResolver(), [], engine_cls=SilentEngine)
    engine.har_path = har_path
    return engine


def test_reproduce_warns_once_about_entries_without_response_body(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    engine: SilentEngine = _silent_engine(tmp_path, _har_with_bodyless_entries(tmp_path, 2, 5))

    engine._reproduce()

    output: str = capsys.readouterr().out
    assert output.count("WARNING:") == 1
    assert "2 de 5 entries do HAR não têm corpo de resposta gravado" in output


def test_reproduce_is_silent_when_every_entry_has_a_body(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    engine: SilentEngine = _silent_engine(tmp_path, _har_with_bodyless_entries(tmp_path, 0, 5))

    engine._reproduce()

    assert "WARNING:" not in capsys.readouterr().out


def test_reproduce_keeps_returning_the_final_validation_result(tmp_path: Path) -> None:
    engine: SilentEngine = _silent_engine(tmp_path, _har_with_bodyless_entries(tmp_path, 2, 5))

    assert engine._reproduce() is True


def _step_with_curl(index: int, url: str, curl_template: str) -> Step:
    return Step(
        index=index,
        request=StepRequest(url=url, method="GET"),
        response=StepResponse(status_code=200),
        analysis=StepAnalysis(step_index=index, curl_template=curl_template),
    )


def test_attempt_step_overrides_curl_cookie_with_jar_state_before_sending(tmp_path: Path) -> None:
    jar: CookieJar = CookieJar()
    jar.feed("exemplo.com", 443, {"sess": "abc"}, {})
    transport: StubHttpTransport = StubHttpTransport(StepResponse(status_code=200))
    engine: Engine = _engine(
        tmp_path, FakeTokenResolver(), [], http_transport=transport, cookie_jar=jar,
    )
    step: Step = _step_with_curl(0, "https://exemplo.com/login", "curl --cookie 'sess=old' https://exemplo.com/login")

    engine._attempt_step(step)

    assert "sess=abc" in transport.calls[0].curl_literal
    assert "sess=old" not in transport.calls[0].curl_literal


def test_attempt_step_feeds_jar_from_response_set_cookie(tmp_path: Path) -> None:
    jar: CookieJar = CookieJar()
    response: StepResponse = StepResponse(
        status_code=200, cookies={"sess": "abc"}, cookie_attributes={"sess": CookieAttributes()},
    )
    transport: StubHttpTransport = StubHttpTransport(response)
    engine: Engine = _engine(
        tmp_path, FakeTokenResolver(), [], http_transport=transport, cookie_jar=jar,
    )
    step: Step = _step_with_curl(0, "https://exemplo.com/login", "curl https://exemplo.com/login")

    engine._attempt_step(step)

    assert jar.current("exemplo.com", 443, "/") == {"sess": "abc"}


def test_attempt_step_adds_cookie_flag_when_curl_has_none_but_jar_has_cookie(tmp_path: Path) -> None:
    jar: CookieJar = CookieJar()
    jar.feed("exemplo.com", 443, {"sess": "abc"}, {})
    transport: StubHttpTransport = StubHttpTransport(StepResponse(status_code=200))
    engine: Engine = _engine(
        tmp_path, FakeTokenResolver(), [], http_transport=transport, cookie_jar=jar,
    )
    step: Step = _step_with_curl(0, "https://exemplo.com/login", "curl https://exemplo.com/login")

    engine._attempt_step(step)

    assert "--cookie" in transport.calls[0].curl_literal
    assert "sess=abc" in transport.calls[0].curl_literal


def test_attempt_step_crashes_when_request_url_is_templated_without_separator(tmp_path: Path) -> None:
    transport: StubHttpTransport = StubHttpTransport(StepResponse(status_code=200))
    engine: Engine = _engine(
        tmp_path, FakeTokenResolver(), [], http_transport=transport, cookie_jar=CookieJar(),
    )
    step: Step = _step_with_curl(
        0, "https://exemplo.com{{extractor:abc123}}", "curl https://exemplo.com/pagina",
    )

    with pytest.raises(ValueError):
        engine._attempt_step(step)


def test_execute_step_retry_feeds_jar_from_first_attempt_before_second_attempt_sends(tmp_path: Path) -> None:
    first_response: StepResponse = StepResponse(
        status_code=401, cookies={"sess": "abc"}, cookie_attributes={"sess": CookieAttributes()},
    )
    second_response: StepResponse = StepResponse(status_code=200)
    transport: StubHttpTransport = StubHttpTransport([first_response, second_response])
    jar: CookieJar = CookieJar()
    engine: Engine = _engine(
        tmp_path, FakeTokenResolver(), [], http_transport=transport, cookie_jar=jar,
    )
    engine.comparator = ReplayResultComparator(Workspace(tmp_path))
    Workspace(tmp_path).original_response_file(0).write_text(
        StepResponse(status_code=200).model_dump_json(), encoding="utf-8"
    )
    step: Step = _step_with_curl(0, "https://exemplo.com/login", "curl https://exemplo.com/login")

    engine.execute_step(step)

    assert len(transport.calls) == 2
    assert "sess=abc" in transport.calls[1].curl_literal
