from pathlib import Path
from typing import Any, Dict, List, Optional

from langchain_core.messages import AIMessage

from har_reproducer.agents.base_agent import BaseAgent
from har_reproducer.contracts import Strategy
from har_reproducer.fs_io.workspace import Workspace
from har_reproducer.models import Extractor, ScriptExecutionResult
from tests.support.fake_script_executor import FakeScriptExecutor
from tests.support.fake_sleeper import FakeSleeper


class LiteralAgent(BaseAgent):

    def __init__(self, strategies: List[Strategy], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._configured_strategies: List[Strategy] = strategies

    def deterministic_strategies(self) -> List[Strategy]:
        return self._configured_strategies


def _always_none(last_error: Optional[str] = None) -> Optional[str]:
    return None


def _fixed_code(code: str) -> Strategy:
    def strategy(last_error: Optional[str] = None) -> Optional[str]:
        return code

    return strategy


def _agent(
        tmp_path: Path,
        strategies: List[Strategy],
        script_executor: FakeScriptExecutor,
        sleeper: FakeSleeper,
        expected_value: str = "segredo",
        path: Optional[str] = None,
        origin_key: Optional[str] = None,
) -> LiteralAgent:
    return LiteralAgent(
        strategies,
        token_id="tok",
        response_sample={},
        expected_value=expected_value,
        workspace=Workspace(tmp_path),
        script_executor=script_executor,
        sleeper=sleeper,
        path=path,
        origin_key=origin_key,
    )


def test_key_prefers_origin_key_over_destination_path(tmp_path: Path) -> None:
    agent: LiteralAgent = _agent(
        tmp_path, [], FakeScriptExecutor([]), FakeSleeper(), path="header:If-None-Match", origin_key="ETag"
    )

    assert agent.key == "ETag"


def test_key_falls_back_to_path_without_origin_key(tmp_path: Path) -> None:
    agent: LiteralAgent = _agent(
        tmp_path, [], FakeScriptExecutor([]), FakeSleeper(), path="header:If-None-Match", origin_key=None
    )

    assert agent.key == "If-None-Match"


def test_key_is_none_without_path_and_without_origin_key(tmp_path: Path) -> None:
    agent: LiteralAgent = _agent(tmp_path, [], FakeScriptExecutor([]), FakeSleeper(), path=None, origin_key=None)

    assert agent.key is None


def test_key_splits_path_after_first_colon(tmp_path: Path) -> None:
    agent: LiteralAgent = _agent(tmp_path, [], FakeScriptExecutor([]), FakeSleeper(), path="header:X-Csrf")

    assert agent.key == "X-Csrf"


def test_key_without_colon_returns_whole_path(tmp_path: Path) -> None:
    agent: LiteralAgent = _agent(tmp_path, [], FakeScriptExecutor([]), FakeSleeper(), path="url")

    assert agent.key == "url"


def test_key_is_none_without_path(tmp_path: Path) -> None:
    agent: LiteralAgent = _agent(tmp_path, [], FakeScriptExecutor([]), FakeSleeper(), path=None)

    assert agent.key is None


def test_value_char_class_uses_word_class_for_safe_value(tmp_path: Path) -> None:
    agent: LiteralAgent = _agent(
        tmp_path, [], FakeScriptExecutor([]), FakeSleeper(), expected_value="abc-123.x"
    )

    assert agent.value_char_class() == r"[\w\-.]+"


def test_value_char_class_falls_back_to_generic_for_unsafe_value(tmp_path: Path) -> None:
    agent: LiteralAgent = _agent(tmp_path, [], FakeScriptExecutor([]), FakeSleeper(), expected_value="a b")

    assert agent.value_char_class() == r".+?"


def test_lazy_value_char_class_makes_plus_lazy(tmp_path: Path) -> None:
    agent: LiteralAgent = _agent(
        tmp_path, [], FakeScriptExecutor([]), FakeSleeper(), expected_value="abc-123.x"
    )

    assert agent.lazy_value_char_class() == r"[\w\-.]+?"


def test_generate_code_skips_none_strategy_and_returns_next_valid_code(tmp_path: Path) -> None:
    agent: LiteralAgent = _agent(
        tmp_path, [_always_none, _fixed_code("def extract_tok(response): return 'x'")],
        FakeScriptExecutor([]), FakeSleeper(),
    )

    code: Optional[str] = agent.generate_code()

    assert code == "def extract_tok(response): return 'x'"


def test_extract_code_block_extracts_fenced_python_block() -> None:
    text: str = "texto\n```python\ndef f(): pass\n```\nfim"

    assert BaseAgent._extract_code_block(text) == "def f(): pass"


def test_extract_code_block_returns_stripped_text_without_fence() -> None:
    assert BaseAgent._extract_code_block("  sem bloco de codigo  ") == "sem bloco de codigo"


def test_response_to_text_concatenates_text_parts_from_list_content() -> None:
    message: AIMessage = AIMessage(content=[{"type": "text", "text": "a"}, "b", {"other": 1}])

    assert BaseAgent._response_to_text(message) == "ab"


def test_run_tdd_loop_succeeds_on_second_attempt_and_sleeps_once_between_attempts(tmp_path: Path) -> None:
    script_executor: FakeScriptExecutor = FakeScriptExecutor([
        ScriptExecutionResult(timed_out=False, return_code=1, stdout="", stderr="falhou"),
        ScriptExecutionResult(timed_out=False, return_code=0, stdout="segredo", stderr=""),
    ])
    sleeper: FakeSleeper = FakeSleeper()
    agent: LiteralAgent = _agent(
        tmp_path,
        [_fixed_code("def extract_tok(response): return 'segredo'")] * 2,
        script_executor, sleeper,
    )

    extractor: Optional[Extractor] = agent.run_tdd_loop(origin_step=0)

    assert extractor is not None
    assert extractor.verified is True
    assert len(sleeper.calls) == 1


def test_run_tdd_loop_returns_none_and_cleans_temp_file_when_exhausted(tmp_path: Path) -> None:
    workspace: Workspace = Workspace(tmp_path)
    agent: LiteralAgent = LiteralAgent(
        [],
        token_id="tok",
        response_sample={},
        expected_value="segredo",
        workspace=workspace,
        script_executor=FakeScriptExecutor([]),
        sleeper=FakeSleeper(),
    )

    extractor: Optional[Extractor] = agent.run_tdd_loop(origin_step=0)

    assert extractor is None
    assert not workspace.temp_extractor_file(agent.safe_token_id).exists()


def test_run_tdd_loop_sleeps_only_between_failed_attempts(tmp_path: Path) -> None:
    script_executor: FakeScriptExecutor = FakeScriptExecutor([
        ScriptExecutionResult(timed_out=False, return_code=1, stdout="", stderr="falhou"),
        ScriptExecutionResult(timed_out=False, return_code=1, stdout="", stderr="falhou"),
        ScriptExecutionResult(timed_out=False, return_code=1, stdout="", stderr="falhou"),
    ])
    sleeper: FakeSleeper = FakeSleeper()
    agent: LiteralAgent = _agent(
        tmp_path,
        [_fixed_code("def extract_tok(response): return 'segredo'")] * 3,
        script_executor, sleeper,
    )

    extractor: Optional[Extractor] = agent.run_tdd_loop(origin_step=0, max_attempts=3)

    assert extractor is None
    assert len(sleeper.calls) == 2


def test_run_tdd_loop_single_attempt_does_not_sleep(tmp_path: Path) -> None:
    script_executor: FakeScriptExecutor = FakeScriptExecutor([
        ScriptExecutionResult(timed_out=False, return_code=1, stdout="", stderr="falhou"),
    ])
    sleeper: FakeSleeper = FakeSleeper()
    agent: LiteralAgent = _agent(
        tmp_path,
        [_fixed_code("def extract_tok(response): return 'segredo'")],
        script_executor, sleeper,
    )

    extractor: Optional[Extractor] = agent.run_tdd_loop(origin_step=0, max_attempts=1)

    assert extractor is None
    assert len(sleeper.calls) == 0
