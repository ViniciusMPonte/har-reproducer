from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from har_reproducer.agents.cookie_agent import CookieAgent
from har_reproducer.agents.css_agent import CSSAgent
from har_reproducer.agents.header_agent import HeaderAgent
from har_reproducer.agents.jsonpath_agent import JSONPathAgent
from har_reproducer.agents.regex_agent import RegexAgent
from har_reproducer.fs_io.workspace import Workspace
from tests.support.fake_script_executor import FakeScriptExecutor
from tests.support.fake_sleeper import FakeSleeper


def _cookie_agent(tmp_path: Path, response_sample: Dict[str, Any], expected_value: str, path: str) -> CookieAgent:
    return CookieAgent(
        token_id="tok", response_sample=response_sample, expected_value=expected_value,
        workspace=Workspace(tmp_path), script_executor=FakeScriptExecutor([]), sleeper=FakeSleeper(), path=path,
    )


def _header_agent(tmp_path: Path, response_sample: Dict[str, Any], expected_value: str, path: str) -> HeaderAgent:
    return HeaderAgent(
        token_id="tok", response_sample=response_sample, expected_value=expected_value,
        workspace=Workspace(tmp_path), script_executor=FakeScriptExecutor([]), sleeper=FakeSleeper(), path=path,
    )


def _jsonpath_agent(tmp_path: Path, response_sample: Dict[str, Any], expected_value: str) -> JSONPathAgent:
    return JSONPathAgent(
        token_id="tok", response_sample=response_sample, expected_value=expected_value,
        workspace=Workspace(tmp_path), script_executor=FakeScriptExecutor([]), sleeper=FakeSleeper(),
    )


def _css_agent(tmp_path: Path, response_sample: Dict[str, Any], expected_value: str) -> CSSAgent:
    return CSSAgent(
        token_id="tok", response_sample=response_sample, expected_value=expected_value,
        workspace=Workspace(tmp_path), script_executor=FakeScriptExecutor([]), sleeper=FakeSleeper(),
    )


def _regex_agent(tmp_path: Path, response_sample: Dict[str, Any], expected_value: str, path: Optional[str]) -> RegexAgent:
    return RegexAgent(
        token_id="tok", response_sample=response_sample, expected_value=expected_value,
        workspace=Workspace(tmp_path), script_executor=FakeScriptExecutor([]), sleeper=FakeSleeper(), path=path,
    )


def test_cookie_agent_context_pattern_anchors_end_of_value_at_string_end(tmp_path: Path) -> None:
    agent: CookieAgent = _cookie_agent(
        tmp_path, {"cookies": {"sid": "prefixTOKEN"}}, "TOKEN", "cookie:sid"
    )

    pattern: Optional[str] = agent._context_pattern()

    assert pattern is not None
    assert pattern.endswith("$")


def test_header_agent_by_name_generates_case_insensitive_fallback(tmp_path: Path) -> None:
    agent: HeaderAgent = _header_agent(
        tmp_path, {"headers": {"X-Token": "abc"}}, "abc", "header:x-token"
    )

    code: Optional[str] = agent._by_name()

    assert code is not None
    assert "lowered" in code
    assert "x-token" in code


def test_jsonpath_agent_returns_no_paths_for_non_json_body(tmp_path: Path) -> None:
    agent: JSONPathAgent = _jsonpath_agent(tmp_path, {"body": "não é json"}, "X")

    assert agent._find_value_paths() == []


def test_jsonpath_agent_finds_nested_path_for_matching_value(tmp_path: Path) -> None:
    agent: JSONPathAgent = _jsonpath_agent(tmp_path, {"body": '{"data":{"token":"X"}}'}, "X")

    paths: List[List[Tuple[str, Any]]] = agent._find_value_paths()

    assert [("key", "data"), ("key", "token")] in paths


def test_css_agent_discards_selector_when_class_is_not_unique(tmp_path: Path) -> None:
    html: str = '<div class="tok">v</div><span class="tok">v</span>'
    agent: CSSAgent = _css_agent(tmp_path, {"body": html}, "v")

    candidates: List[Tuple[int, str, str]] = agent._rank_candidates()

    assert not any(selector == ".tok" for _, selector, _ in candidates)


def test_regex_agent_key_pattern_is_none_for_body_key(tmp_path: Path) -> None:
    agent: RegexAgent = _regex_agent(tmp_path, {}, "v", "body")

    assert agent._key_pattern() is None


def test_regex_agent_key_pattern_escapes_key_for_other_paths(tmp_path: Path) -> None:
    agent: RegexAgent = _regex_agent(tmp_path, {}, "v", "foo:bar")

    pattern: Optional[str] = agent._key_pattern()

    assert pattern is not None
    assert "bar" in pattern
