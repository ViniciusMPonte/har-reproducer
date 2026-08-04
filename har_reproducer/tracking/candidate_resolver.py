import hashlib
import json
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar, Dict, List, Optional, Tuple, Type

from langchain_core.language_models import BaseChatModel

from har_reproducer.agents import BaseAgent, CookieAgent, CSSAgent, HeaderAgent, JSONPathAgent, RegexAgent
from har_reproducer.models import AgentType, DynamicToken, Extractor, TokenLocation
from har_reproducer.reproduction import ExtractorMetadataStore, ExtractorRunner
from har_reproducer.session import SessionStore
from har_reproducer.templates import IdentifierSanitizer
from har_reproducer.tracking.response_grep import ResponseGrep
from har_reproducer.tracking.token_location_detector import TokenLocationDetector


class SlotStatus(str, Enum):
    MATCH = "Match"
    MISMATCH = "Mismatch"
    FREE = "Free"


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
        self.extractor_runner: ExtractorRunner = ExtractorRunner()
        self.metadata_store: ExtractorMetadataStore = ExtractorMetadataStore()
        self._validated_values: Dict[str, str] = {}

    def resolve(self, candidates: List[DynamicToken]) -> List[DynamicToken]:
        return [self._process_candidate(candidate) for candidate in candidates]

    def _process_candidate(self, candidate: DynamicToken) -> DynamicToken:
        origin: Optional[Tuple[int, str]] = ResponseGrep.find(
            self.responses_dir, candidate.current_value
        )
        if not origin:
            candidate.status = "NotFound"
            return candidate

        candidate.origin_step = origin[0]
        candidate.token_id = self._derive_token_id(candidate.path, candidate.origin_step)

        if self._reuse_verified_in_memory(candidate):
            return candidate

        reused: bool
        initial_error: Optional[str]
        reused, initial_error = self._reuse_persisted_from_disk(candidate)
        if reused:
            return candidate

        return self._generate_new_extractor(candidate, initial_error)

    def _reuse_verified_in_memory(self, candidate: DynamicToken) -> bool:
        existing: Optional[Extractor] = self.session_store.state.registry.get(candidate.token_id)
        if existing is None or not existing.verified:
            return False
        candidate.status = "Resolved"
        return True

    def _reuse_persisted_from_disk(self, candidate: DynamicToken) -> Tuple[bool, Optional[str]]:
        persisted: Optional[Extractor] = self.metadata_store.load(candidate.token_id)
        if persisted is None:
            return False, None

        result: Optional[str] = self.extractor_runner.run_existing(candidate.token_id)
        if result == candidate.current_value:
            self.session_store.state.registry[candidate.token_id] = persisted
            candidate.status = "Resolved"
            return True, None

        return False, self._mismatch_error(result, candidate.current_value)

    def _find_slot(self, base_token_id: str, candidate: DynamicToken) -> Tuple[str, Optional[str]]:
        attempt: int = 1
        last_error: Optional[str] = None
        while True:
            slot_id: str = base_token_id if attempt == 1 else self._fork_token_id(base_token_id, attempt)
            status: SlotStatus
            error: Optional[str]
            status, error = self._check_slot(slot_id, candidate)
            if status == SlotStatus.MATCH:
                return slot_id, None
            if status == SlotStatus.FREE:
                return slot_id, last_error
            last_error = error
            attempt += 1

    def _check_slot(self, slot_id: str, candidate: DynamicToken) -> Tuple[SlotStatus, Optional[str]]:
        cached: Optional[Tuple[SlotStatus, Optional[str]]] = self._check_cached_slot(slot_id, candidate)
        if cached is not None:
            return cached
        return self._check_persisted_slot(slot_id, candidate)

    def _check_cached_slot(
            self, slot_id: str, candidate: DynamicToken
    ) -> Optional[Tuple[SlotStatus, Optional[str]]]:
        cached_value: Optional[str] = self._validated_values.get(slot_id)
        if cached_value is None:
            return None
        if cached_value == candidate.current_value:
            return SlotStatus.MATCH, None
        return SlotStatus.MISMATCH, self._mismatch_error(cached_value, candidate.current_value)

    def _check_persisted_slot(self, slot_id: str, candidate: DynamicToken) -> Tuple[SlotStatus, Optional[str]]:
        persisted: Optional[Extractor] = self.metadata_store.load(slot_id)
        if persisted is None:
            return SlotStatus.FREE, None

        result: Optional[str] = self.extractor_runner.run_existing(slot_id)
        if result != candidate.current_value:
            return SlotStatus.MISMATCH, self._mismatch_error(result, candidate.current_value)

        self._accept_persisted_slot(slot_id, persisted, result)
        return SlotStatus.MATCH, None

    def _accept_persisted_slot(self, slot_id: str, persisted: Extractor, result: str) -> None:
        self.session_store.state.registry[slot_id] = persisted
        self.session_store.set_token(slot_id, result)
        self._validated_values[slot_id] = result

    def _generate_new_extractor(self, candidate: DynamicToken, initial_error: Optional[str]) -> DynamicToken:
        candidate.status = "UnderReview"

        response_sample: Optional[Dict[str, Any]] = self._load_response(candidate.origin_step)
        if response_sample is None:
            return candidate

        candidate.origin_location = TokenLocationDetector.find(candidate.current_value, response_sample)
        self._register_extractor(candidate, response_sample, initial_error)
        return candidate

    @staticmethod
    def _derive_token_id(path: str, origin_step: int) -> str:
        return hashlib.md5(f"{path}:{origin_step}".encode("utf-8")).hexdigest()

    @staticmethod
    def _fork_token_id(base_token_id: str, attempt: int) -> str:
        return hashlib.md5(f"{base_token_id}:{attempt}".encode("utf-8")).hexdigest()

    @staticmethod
    def _mismatch_error(result: Optional[str], expected: str) -> str:
        if result is None:
            return "Persisted extractor failed to execute (no output)."
        return f"Persisted extractor output mismatch: got {result!r}, expected {expected!r}"

    def _register_extractor(
            self,
            candidate: DynamicToken,
            response_sample: Dict[str, Any],
            initial_error: Optional[str] = None,
    ) -> None:
        new_extractor: Optional[Extractor] = self._generate_extractor(candidate, response_sample, initial_error)
        if new_extractor is not None:
            self.session_store.state.registry[candidate.token_id] = new_extractor
            self.metadata_store.save(new_extractor)
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
            self,
            candidate: DynamicToken,
            response_sample: Dict[str, Any],
            initial_error: Optional[str] = None,
    ) -> Optional[Extractor]:
        if candidate.origin_location is None:
            return self._build_literal_extractor(candidate, AgentType.LITERAL)

        agent_cls: Type[BaseAgent] = self.LOCATION_AGENTS.get(candidate.origin_location, RegexAgent)

        agent: BaseAgent = agent_cls(
            token_id=candidate.token_id,
            response_sample=response_sample,
            expected_value=candidate.current_value,
            path=candidate.path,
            location=candidate.origin_location.value if candidate.origin_location else None,
            llm=self.llm,
        )
        extractor: Optional[Extractor] = agent.run_tdd_loop(
            origin_step=candidate.origin_step, initial_error=initial_error
        )
        if extractor is not None:
            return extractor

        candidate.extraction_exhausted = True
        return self._build_literal_extractor(candidate, AgentType.LITERAL_FALLBACK)

    @staticmethod
    def _build_literal_extractor(candidate: DynamicToken, agent_type: AgentType) -> Extractor:
        safe_token_id: str = IdentifierSanitizer.sanitize(candidate.token_id)
        return Extractor(
            token_id=candidate.token_id,
            code=f"def extract_{safe_token_id}(response):\n    return {candidate.current_value!r}\n",
            verified=True,
            agent_type=agent_type,
            origin_step=candidate.origin_step,
        )
