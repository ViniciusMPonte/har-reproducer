import hashlib
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from har_reproducer.agents import AgentFactory, BaseAgent
from har_reproducer.models import AgentType, DynamicToken, Extractor, OriginMatch
from har_reproducer.reproduction import ExtractorMetadataStore, ExtractorRunner
from har_reproducer.session import SessionStore
from har_reproducer.templates import IdentifierSanitizer
from har_reproducer.tracking.origin_finder import OriginFinder
from har_reproducer.tracking.response_corpus import ResponseCorpus
from har_reproducer.tracking.token_location_detector import TokenLocationDetector


class SlotStatus(str, Enum):
    MATCH = "Match"
    MISMATCH = "Mismatch"
    FREE = "Free"


class CandidateResolver:

    def __init__(
            self,
            response_corpus: ResponseCorpus,
            origin_finder: OriginFinder,
            session_store: SessionStore,
            extractor_runner: ExtractorRunner,
            metadata_store: ExtractorMetadataStore,
            agent_factory: AgentFactory,
    ) -> None:
        self.response_corpus: ResponseCorpus = response_corpus
        self.origin_finder: OriginFinder = origin_finder
        self.session_store: SessionStore = session_store
        self.extractor_runner: ExtractorRunner = extractor_runner
        self.metadata_store: ExtractorMetadataStore = metadata_store
        self.agent_factory: AgentFactory = agent_factory
        self._validated_values: Dict[str, str] = {}
        self._origin_cache: Dict[str, OriginMatch] = {}
        self._origin_misses: Dict[str, int] = {}

    def resolve(self, candidates: List[DynamicToken], step_index: int) -> List[DynamicToken]:
        return [self._process_candidate(candidate, step_index) for candidate in candidates]

    def _process_candidate(self, candidate: DynamicToken, step_index: int) -> DynamicToken:
        origin: Optional[OriginMatch] = self._find_origin(candidate.current_value, step_index)
        if origin is None:
            candidate.status = "NotFound"
            return candidate

        candidate.origin_step = origin.step_index
        candidate.origin_key = origin.origin_key
        candidate.origin_container = origin.origin_container
        base_token_id: str = self._derive_token_id(candidate.path, candidate.origin_step)

        slot_id: str
        initial_error: Optional[str]
        slot_id, initial_error = self._find_slot(base_token_id, candidate)
        candidate.token_id = slot_id

        if self.session_store.state.registry.get(slot_id) is not None:
            candidate.status = "Resolved"
            return candidate

        return self._generate_new_extractor(candidate, initial_error)

    def _find_origin(self, value: str, step_index: int) -> Optional[OriginMatch]:
        cached_origin: Optional[OriginMatch] = self._origin_cache.get(value)
        if cached_origin is not None:
            return cached_origin

        from_step_index: int = self._origin_misses.get(value, 0)
        origin: Optional[OriginMatch] = self.origin_finder.find(value, from_step_index, step_index)
        if origin is None:
            self._origin_misses[value] = step_index
            return None

        self._origin_cache[value] = origin
        return origin

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

        result: Optional[str] = self.extractor_runner.run_existing(slot_id, self.response_corpus.responses_dir)
        if result != candidate.current_value:
            return SlotStatus.MISMATCH, self._mismatch_error(result, candidate.current_value)

        self._accept_persisted_slot(slot_id, persisted, result)
        return SlotStatus.MATCH, None

    def _accept_persisted_slot(self, slot_id: str, persisted: Extractor, result: str) -> None:
        if persisted.captured_value is None:
            persisted.captured_value = result
            self.metadata_store.save(persisted)
        self.session_store.state.registry[slot_id] = persisted
        self.session_store.set_token(slot_id, result)
        self._validated_values[slot_id] = result

    def _generate_new_extractor(self, candidate: DynamicToken, initial_error: Optional[str]) -> DynamicToken:
        candidate.status = "UnderReview"

        response_sample: Optional[Dict[str, Any]] = self.response_corpus.response(candidate.origin_step)
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
            new_extractor.captured_value = candidate.current_value
            self.session_store.state.registry[candidate.token_id] = new_extractor
            self.metadata_store.save(new_extractor)
            candidate.status = "Resolved"
        else:
            candidate.status = "Unresolved"

    def _generate_extractor(
            self,
            candidate: DynamicToken,
            response_sample: Dict[str, Any],
            initial_error: Optional[str] = None,
    ) -> Optional[Extractor]:
        if candidate.origin_location is None:
            return self._build_literal_extractor(candidate, AgentType.LITERAL)

        agent: BaseAgent = self.agent_factory.create(candidate, response_sample)
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
