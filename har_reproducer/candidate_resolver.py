import hashlib
import json
from pathlib import Path
from typing import Any, ClassVar, Dict, List, Optional, Tuple, Type

from langchain_core.language_models import BaseChatModel

from .agents import BaseAgent, CookieAgent, CSSAgent, HeaderAgent, JSONPathAgent, RegexAgent
from .grep_utils import ResponseGrep
from .models import DynamicToken, Extractor, TokenLocation
from .session import SessionStore
from .token_location_detector import TokenLocationDetector


class CandidateResolver:
    LOCATION_AGENTS: ClassVar[Dict[TokenLocation, Type[BaseAgent]]] = {
        TokenLocation.COOKIE: CookieAgent,
        TokenLocation.HEADER: HeaderAgent,
        TokenLocation.BODY_JSON: JSONPathAgent,
        TokenLocation.BODY_HTML: CSSAgent,
        TokenLocation.SCRIPT: RegexAgent,
    }

    def __init__(
            self,
            responses_dir: Path,
            session_store: SessionStore,
            llm: Optional[BaseChatModel],
    ) -> None:
        self.responses_dir: Path = responses_dir
        self.session_store: SessionStore = session_store
        self.llm: Optional[BaseChatModel] = llm

    def resolve(self, candidates: List[DynamicToken]) -> List[DynamicToken]:
        return [self._process_candidate(candidate) for candidate in candidates]

    def _process_candidate(self, candidate: DynamicToken) -> DynamicToken:
        origin: Optional[Tuple[int, str]] = ResponseGrep.find(
            self.responses_dir, candidate.current_value
        )
        if not origin:
            candidate.status = "NotFound"
            return candidate

        origin_step: int = origin[0]
        candidate.origin_step = origin_step
        candidate.token_id = self._derive_token_id(candidate.path, origin_step)

        existing: Optional[Extractor] = self.session_store.state.registry.get(candidate.token_id)
        if existing is not None and existing.verified:
            candidate.status = "Resolved"
            return candidate

        candidate.status = "UnderReview"

        response_sample: Optional[Dict[str, Any]] = self._load_response(origin_step)
        if response_sample is None:
            return candidate

        candidate.origin_location = TokenLocationDetector.find(candidate.current_value, response_sample)
        self._register_extractor(candidate, response_sample)
        return candidate

    @staticmethod
    def _derive_token_id(path: str, origin_step: int) -> str:
        return hashlib.md5(f"{path}:{origin_step}".encode("utf-8")).hexdigest()

    def _register_extractor(self, candidate: DynamicToken, response_sample: Dict[str, Any]) -> None:
        new_extractor: Optional[Extractor] = self._generate_extractor(candidate, response_sample)
        if new_extractor is not None:
            self.session_store.state.registry[candidate.token_id] = new_extractor
            candidate.status = "Resolved"
        else:
            candidate.status = "Unresolved"

    def _load_response(self, step_index: int) -> Optional[Dict[str, Any]]:
        res_file: Path = self.responses_dir / f"res_{step_index:04d}.json"
        if not res_file.exists():
            return None
        try:
            data: Dict[str, Any] = json.loads(res_file.read_text(encoding="utf-8"))
            return data
        except Exception as e:
            print(f"[AVISO] Falha ao carregar response do step {step_index}: {e}")
            return None

    def _generate_extractor(
            self, candidate: DynamicToken, response_sample: Dict[str, Any]
    ) -> Optional[Extractor]:
        agent_cls: Type[BaseAgent] = self.LOCATION_AGENTS.get(candidate.origin_location, RegexAgent)

        agent: BaseAgent = agent_cls(
            token_id=candidate.token_id,
            response_sample=response_sample,
            expected_value=candidate.current_value,
            path=candidate.path,
            location=candidate.origin_location.value if candidate.origin_location else None,
            llm=self.llm,
        )
        return agent.run_tdd_loop(origin_step=candidate.origin_step)
