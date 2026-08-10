from pathlib import Path
from typing import Optional

import pytest

from har_reproducer.fs_io.workspace import Workspace
from har_reproducer.models import AgentType, Extractor, ScriptExecutionResult
from har_reproducer.reproduction.extractor_runner import ExtractorRunner
from tests.support.fake_script_executor import FakeScriptExecutor


def test_run_raises_value_error_without_origin_step(tmp_path: Path) -> None:
    runner: ExtractorRunner = ExtractorRunner(Workspace(tmp_path), FakeScriptExecutor([]))
    extractor: Extractor = Extractor(
        token_id="t1", code="def f(r): pass", agent_type=AgentType.REGEX, origin_step=None
    )

    with pytest.raises(ValueError):
        runner.run(extractor)


def test_run_existing_returns_none_when_file_missing(tmp_path: Path) -> None:
    fake_executor: FakeScriptExecutor = FakeScriptExecutor([])
    runner: ExtractorRunner = ExtractorRunner(Workspace(tmp_path), fake_executor)

    result: Optional[str] = runner.run_existing("token-sem-arquivo")

    assert result is None
    assert fake_executor.calls == []


def test_run_returns_stripped_stdout_on_success(tmp_path: Path) -> None:
    fake_executor: FakeScriptExecutor = FakeScriptExecutor(
        [ScriptExecutionResult(timed_out=False, return_code=0, stdout="  valor  \n", stderr="")]
    )
    runner: ExtractorRunner = ExtractorRunner(Workspace(tmp_path), fake_executor)
    extractor: Extractor = Extractor(token_id="t1", code="def f(r): pass", agent_type=AgentType.REGEX, origin_step=0)

    result: Optional[str] = runner.run(extractor)

    assert result == "valor"


def test_run_returns_none_on_non_zero_return_code(tmp_path: Path) -> None:
    fake_executor: FakeScriptExecutor = FakeScriptExecutor(
        [ScriptExecutionResult(timed_out=False, return_code=1, stdout="", stderr="erro")]
    )
    runner: ExtractorRunner = ExtractorRunner(Workspace(tmp_path), fake_executor)
    extractor: Extractor = Extractor(token_id="t1", code="def f(r): pass", agent_type=AgentType.REGEX, origin_step=0)

    result: Optional[str] = runner.run(extractor)

    assert result is None


def test_run_returns_none_when_executor_raises(tmp_path: Path) -> None:
    fake_executor: FakeScriptExecutor = FakeScriptExecutor([RuntimeError("boom")])
    runner: ExtractorRunner = ExtractorRunner(Workspace(tmp_path), fake_executor)
    extractor: Extractor = Extractor(token_id="t1", code="def f(r): pass", agent_type=AgentType.REGEX, origin_step=0)

    result: Optional[str] = runner.run(extractor)

    assert result is None


def test_build_env_omits_override_dir_when_none() -> None:
    env: dict = ExtractorRunner._build_env(None)

    assert "HAR_REPRODUCER_RESPONSE_OVERRIDE_DIR" not in env


def test_build_env_includes_override_dir_when_provided() -> None:
    env: dict = ExtractorRunner._build_env(Path("/x"))

    assert env["HAR_REPRODUCER_RESPONSE_OVERRIDE_DIR"] == "/x"
