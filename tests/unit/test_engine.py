import json
from pathlib import Path
from typing import Any, Dict, List, NamedTuple

import pytest

from har_reproducer.engines.dry_engine import DryEngine
from har_reproducer.engines.engine import Engine
from har_reproducer.fs_io.workspace import Workspace
from har_reproducer.models import SkipRulesConfig, Step, StepRequest, StepResponse, SuccessCriterion
from har_reproducer.replay.replay_result_comparator import ReplayResultComparator
from har_reproducer.reproduction.step_retry_policy import StepRetryPolicy
from har_reproducer.reproduction.step_skip_evaluator import StepSkipEvaluator
from har_reproducer.session.session_store import SessionStore
from har_reproducer.validation.validator import Validator


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
) -> Engine:
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
        http_transport=None,
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
