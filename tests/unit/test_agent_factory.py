from pathlib import Path
from typing import Any, Dict, Optional

from har_reproducer.agents.base_agent import BaseAgent
from har_reproducer.agents.construction.agent_factory import AgentFactory
from har_reproducer.agents.cookie_agent import CookieAgent
from har_reproducer.agents.css_agent import CSSAgent
from har_reproducer.agents.regex_agent import RegexAgent
from har_reproducer.fs_io.workspace import Workspace
from har_reproducer.models import (
    DynamicToken,
    Extractor,
    OriginContainer,
    ScriptExecutionResult,
    TokenLocation,
)
from tests.support.fake_script_executor import FakeScriptExecutor
from tests.support.fake_sleeper import FakeSleeper


def _factory(tmp_path: Path) -> AgentFactory:
    return AgentFactory(Workspace(tmp_path), FakeScriptExecutor([]), FakeSleeper(), None)


def _candidate(location: Optional[TokenLocation], token_id: str = "tok") -> DynamicToken:
    return DynamicToken(
        token_id=token_id, path="header:X", current_value="v", destination_location=TokenLocation.HEADER,
        origin_location=location, status="UnderReview",
    )


def test_create_maps_cookie_location_to_cookie_agent(tmp_path: Path) -> None:
    agent: BaseAgent = _factory(tmp_path).create(_candidate(TokenLocation.COOKIE), {})

    assert isinstance(agent, CookieAgent)


def test_create_maps_body_html_location_to_css_agent(tmp_path: Path) -> None:
    agent: BaseAgent = _factory(tmp_path).create(_candidate(TokenLocation.BODY_HTML), {})

    assert isinstance(agent, CSSAgent)


def test_create_falls_back_to_regex_agent_for_url_param_location(tmp_path: Path) -> None:
    agent: BaseAgent = _factory(tmp_path).create(_candidate(TokenLocation.URL_PARAM), {})

    assert isinstance(agent, RegexAgent)


def test_create_falls_back_to_regex_agent_when_location_is_none(tmp_path: Path) -> None:
    agent: BaseAgent = _factory(tmp_path).create(_candidate(None), {})

    assert isinstance(agent, RegexAgent)


def test_create_propagates_candidate_fields_to_agent(tmp_path: Path) -> None:
    candidate: DynamicToken = _candidate(TokenLocation.COOKIE, token_id="abc")

    agent: BaseAgent = _factory(tmp_path).create(candidate, {})

    assert agent.token_id == "abc"
    assert agent.expected_value == candidate.current_value
    assert agent.path == candidate.path


def _candidate_with_origin(
        origin_location: Optional[TokenLocation],
        origin_container: Optional[OriginContainer],
) -> DynamicToken:
    return DynamicToken(
        token_id="tok", path="header:If-None-Match", current_value="v",
        destination_location=TokenLocation.HEADER, origin_location=origin_location,
        origin_step=1, origin_key="ETag", origin_container=origin_container, status="UnderReview",
    )


def test_create_propagates_origin_key_when_container_agrees_with_location(tmp_path: Path) -> None:
    candidate: DynamicToken = _candidate_with_origin(TokenLocation.HEADER, OriginContainer.HEADER)

    agent: BaseAgent = _factory(tmp_path).create(candidate, {})

    assert agent.origin_key == "ETag"
    assert agent.key == "ETag"


def test_create_propagates_origin_key_for_agreeing_cookie_container(tmp_path: Path) -> None:
    candidate: DynamicToken = _candidate_with_origin(TokenLocation.COOKIE, OriginContainer.COOKIE)

    agent: BaseAgent = _factory(tmp_path).create(candidate, {})

    assert agent.origin_key == "ETag"


def test_create_does_not_propagate_origin_key_when_container_disagrees(tmp_path: Path) -> None:
    candidate: DynamicToken = _candidate_with_origin(TokenLocation.COOKIE, OriginContainer.HEADER)

    agent: BaseAgent = _factory(tmp_path).create(candidate, {})

    assert agent.origin_key is None
    assert agent.key == "If-None-Match"


def test_create_does_not_propagate_origin_key_for_script_location(tmp_path: Path) -> None:
    for container in [OriginContainer.HEADER, OriginContainer.COOKIE]:
        candidate: DynamicToken = _candidate_with_origin(TokenLocation.SCRIPT, container)

        agent: BaseAgent = _factory(tmp_path).create(candidate, {})

        assert agent.origin_key is None


def test_create_does_not_propagate_origin_key_without_container(tmp_path: Path) -> None:
    candidate: DynamicToken = _candidate_with_origin(TokenLocation.HEADER, None)

    agent: BaseAgent = _factory(tmp_path).create(candidate, {})

    assert agent.origin_key is None


def test_header_agent_first_deterministic_strategy_uses_origin_key(tmp_path: Path) -> None:
    candidate: DynamicToken = DynamicToken(
        token_id="tok", path="header:If-None-Match", current_value='W/"9b1-abc"',
        destination_location=TokenLocation.HEADER, origin_location=TokenLocation.HEADER,
        origin_step=1, origin_key="ETag", origin_container=OriginContainer.HEADER, status="UnderReview",
    )
    response_sample: Dict[str, Any] = {"headers": {"ETag": 'W/"9b1-abc"'}}
    script_executor: FakeScriptExecutor = FakeScriptExecutor(
        [ScriptExecutionResult(timed_out=False, return_code=0, stdout='W/"9b1-abc"', stderr="")]
    )
    factory: AgentFactory = AgentFactory(Workspace(tmp_path), script_executor, FakeSleeper(), None)

    agent: BaseAgent = factory.create(candidate, response_sample)
    extractor: Optional[Extractor] = agent.run_tdd_loop(origin_step=1)

    assert extractor is not None
    assert extractor.verified is True
    assert "'ETag'" in extractor.code
    assert len(script_executor.calls) == 1
