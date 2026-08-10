from pathlib import Path
from typing import Optional

from har_reproducer.agents.base_agent import BaseAgent
from har_reproducer.agents.construction.agent_factory import AgentFactory
from har_reproducer.agents.cookie_agent import CookieAgent
from har_reproducer.agents.css_agent import CSSAgent
from har_reproducer.agents.regex_agent import RegexAgent
from har_reproducer.fs_io.workspace import Workspace
from har_reproducer.models import DynamicToken, TokenLocation
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
