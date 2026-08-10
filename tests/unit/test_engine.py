from pathlib import Path
from typing import List, NamedTuple

from har_reproducer.engines.dry_engine import DryEngine
from har_reproducer.engines.engine import Engine
from har_reproducer.fs_io.workspace import Workspace
from har_reproducer.models import SkipRulesConfig, Step, StepRequest, StepResponse, SuccessCriterion
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
        success_criteria=success_criteria,
        http_transport=None,
    )


def test_handle_recovery_does_nothing_for_non_recoverable_status(tmp_path: Path) -> None:
    token_resolver: FakeTokenResolver = FakeTokenResolver()
    engine: Engine = _engine(tmp_path, token_resolver, [])

    handled: bool = engine.handle_recovery(StepResponse(status_code=500))

    assert handled is False
    assert token_resolver.calls == []


def test_handle_recovery_forces_token_refresh_for_recoverable_status(tmp_path: Path) -> None:
    token_resolver: FakeTokenResolver = FakeTokenResolver()
    engine: Engine = _engine(tmp_path, token_resolver, [])

    handled: bool = engine.handle_recovery(StepResponse(status_code=401))

    assert handled is True
    assert token_resolver.calls == [RecordedResolveAllCall(True)]


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
