from typing import Any, ClassVar, Dict, Optional, Type

from langchain_core.language_models import BaseChatModel

from har_reproducer.agents.base_agent import BaseAgent
from har_reproducer.agents.cookie_agent import CookieAgent
from har_reproducer.agents.css_agent import CSSAgent
from har_reproducer.agents.header_agent import HeaderAgent
from har_reproducer.agents.jsonpath_agent import JSONPathAgent
from har_reproducer.agents.regex_agent import RegexAgent
from har_reproducer.models import DynamicToken, TokenLocation


class AgentFactory:
    LOCATION_AGENTS: ClassVar[Dict[TokenLocation, Type[BaseAgent]]] = {
        TokenLocation.COOKIE: CookieAgent,
        TokenLocation.HEADER: HeaderAgent,
        TokenLocation.BODY_JSON: JSONPathAgent,
        TokenLocation.BODY_HTML: CSSAgent,
        TokenLocation.SCRIPT: RegexAgent,
    }
    DEFAULT_AGENT: ClassVar[Type[BaseAgent]] = RegexAgent

    def __init__(self, llm: Optional[BaseChatModel]) -> None:
        self.llm: Optional[BaseChatModel] = llm

    def create(self, candidate: DynamicToken, response_sample: Dict[str, Any]) -> BaseAgent:
        agent_cls: Type[BaseAgent] = self.LOCATION_AGENTS.get(candidate.origin_location, self.DEFAULT_AGENT)

        return agent_cls(
            token_id=candidate.token_id,
            response_sample=response_sample,
            expected_value=candidate.current_value,
            path=candidate.path,
            location=candidate.origin_location.value if candidate.origin_location else None,
            llm=self.llm,
        )
