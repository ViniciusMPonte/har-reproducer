from pathlib import Path
from typing import Optional, Tuple

from har_reproducer.agents.construction.agent_factory import AgentFactory
from har_reproducer.fs_io.workspace import Workspace
from har_reproducer.models import AgentType, DynamicToken, Extractor, TokenLocation
from har_reproducer.session import SessionStore
from har_reproducer.tracking.candidate_resolver import CandidateResolver, SlotStatus
from tests.support.fake_extractor_runner import FakeExtractorRunner
from tests.support.fake_metadata_store import FakeMetadataStore
from tests.support.fake_script_executor import FakeScriptExecutor
from tests.support.fake_sleeper import FakeSleeper


def _candidate(current_value: str) -> DynamicToken:
    return DynamicToken(
        token_id="placeholder",
        path="header:X",
        current_value=current_value,
        destination_location=TokenLocation.HEADER,
        status="UnderReview",
    )


def _resolver(
        tmp_path: Path,
        extractor_runner: FakeExtractorRunner,
        metadata_store: FakeMetadataStore,
) -> CandidateResolver:
    workspace: Workspace = Workspace(tmp_path)
    agent_factory: AgentFactory = AgentFactory(workspace, FakeScriptExecutor([]), FakeSleeper(), None)
    return CandidateResolver(tmp_path, SessionStore(), extractor_runner, metadata_store, agent_factory)


def test_check_cached_slot_matches_when_cached_value_equals_candidate(tmp_path: Path) -> None:
    resolver: CandidateResolver = _resolver(tmp_path, FakeExtractorRunner(), FakeMetadataStore())
    resolver._validated_values["t1"] = "v1"

    result: Optional[Tuple[SlotStatus, Optional[str]]] = resolver._check_cached_slot("t1", _candidate("v1"))

    assert result == (SlotStatus.MATCH, None)


def test_check_cached_slot_mismatches_when_cached_value_differs(tmp_path: Path) -> None:
    resolver: CandidateResolver = _resolver(tmp_path, FakeExtractorRunner(), FakeMetadataStore())
    resolver._validated_values["t1"] = "v1"

    status: SlotStatus
    error: Optional[str]
    status, error = resolver._check_cached_slot("t1", _candidate("v2"))

    assert status == SlotStatus.MISMATCH
    assert error is not None and "v1" in error and "v2" in error


def test_check_persisted_slot_is_free_without_persisted_extractor(tmp_path: Path) -> None:
    resolver: CandidateResolver = _resolver(tmp_path, FakeExtractorRunner(), FakeMetadataStore())

    result: Tuple[SlotStatus, Optional[str]] = resolver._check_persisted_slot("t1", _candidate("v1"))

    assert result == (SlotStatus.FREE, None)


def test_check_persisted_slot_matches_and_accepts_when_rerun_output_equals_candidate(tmp_path: Path) -> None:
    metadata_store: FakeMetadataStore = FakeMetadataStore()
    persisted: Extractor = Extractor(token_id="t1", code="def f(r): pass", agent_type=AgentType.REGEX)
    metadata_store.save(persisted)
    extractor_runner: FakeExtractorRunner = FakeExtractorRunner(run_existing_result="v1")
    resolver: CandidateResolver = _resolver(tmp_path, extractor_runner, metadata_store)

    status: SlotStatus
    error: Optional[str]
    status, error = resolver._check_persisted_slot("t1", _candidate("v1"))

    assert status == SlotStatus.MATCH
    assert error is None
    assert resolver.session_store.state.tokens["t1"] == "v1"


def test_check_persisted_slot_mismatches_when_run_existing_returns_none(tmp_path: Path) -> None:
    metadata_store: FakeMetadataStore = FakeMetadataStore()
    metadata_store.save(Extractor(token_id="t1", code="def f(r): pass", agent_type=AgentType.REGEX))
    extractor_runner: FakeExtractorRunner = FakeExtractorRunner(run_existing_result=None)
    resolver: CandidateResolver = _resolver(tmp_path, extractor_runner, metadata_store)

    status: SlotStatus
    error: Optional[str]
    status, error = resolver._check_persisted_slot("t1", _candidate("v1"))

    assert status == SlotStatus.MISMATCH
    assert error == "Persisted extractor failed to execute (no output)."


def test_find_slot_forks_on_mismatch_and_returns_last_error_on_free_slot(tmp_path: Path) -> None:
    base_token_id: str = "base"
    forked_token_id: str = CandidateResolver._fork_token_id(base_token_id, 2)

    metadata_store: FakeMetadataStore = FakeMetadataStore()
    metadata_store.save(Extractor(token_id=base_token_id, code="def f(r): pass", agent_type=AgentType.REGEX))
    extractor_runner: FakeExtractorRunner = FakeExtractorRunner(run_existing_by_token={base_token_id: "outro-valor"})
    resolver: CandidateResolver = _resolver(tmp_path, extractor_runner, metadata_store)

    slot_id: str
    last_error: Optional[str]
    slot_id, last_error = resolver._find_slot(base_token_id, _candidate("v1"))

    assert slot_id == forked_token_id
    assert last_error is not None and "outro-valor" in last_error


def test_derive_token_id_is_deterministic_and_sensitive_to_origin_step() -> None:
    first: str = CandidateResolver._derive_token_id("cookie:sid", 2)
    second: str = CandidateResolver._derive_token_id("cookie:sid", 2)
    third: str = CandidateResolver._derive_token_id("cookie:sid", 3)

    assert first == second
    assert first != third


def test_register_extractor_persists_captured_value(tmp_path: Path) -> None:
    metadata_store: FakeMetadataStore = FakeMetadataStore()
    resolver: CandidateResolver = _resolver(tmp_path, FakeExtractorRunner(), metadata_store)
    candidate: DynamicToken = _candidate("segredo")
    candidate.token_id = "t1"

    resolver._register_extractor(candidate, response_sample={})

    stored: Optional[Extractor] = metadata_store.load("t1")
    assert stored is not None
    assert stored.captured_value == "segredo"


def test_accept_persisted_slot_backfills_captured_value_when_none(tmp_path: Path) -> None:
    metadata_store: FakeMetadataStore = FakeMetadataStore()
    metadata_store.save(Extractor(token_id="t1", code="def f(r): pass", agent_type=AgentType.REGEX))
    extractor_runner: FakeExtractorRunner = FakeExtractorRunner(run_existing_result="v1")
    resolver: CandidateResolver = _resolver(tmp_path, extractor_runner, metadata_store)

    status: SlotStatus
    error: Optional[str]
    status, error = resolver._check_persisted_slot("t1", _candidate("v1"))

    assert status == SlotStatus.MATCH
    assert error is None
    stored: Optional[Extractor] = metadata_store.load("t1")
    assert stored is not None
    assert stored.captured_value == "v1"


def test_accept_persisted_slot_keeps_existing_captured_value(tmp_path: Path) -> None:
    metadata_store: FakeMetadataStore = FakeMetadataStore()
    metadata_store.save(
        Extractor(token_id="t1", code="def f(r): pass", agent_type=AgentType.REGEX, captured_value="antigo")
    )
    extractor_runner: FakeExtractorRunner = FakeExtractorRunner(run_existing_result="v1")
    resolver: CandidateResolver = _resolver(tmp_path, extractor_runner, metadata_store)

    status: SlotStatus
    error: Optional[str]
    status, error = resolver._check_persisted_slot("t1", _candidate("v1"))

    assert status == SlotStatus.MATCH
    assert error is None
    stored: Optional[Extractor] = metadata_store.load("t1")
    assert stored is not None
    assert stored.captured_value == "antigo"


def test_build_literal_extractor_returns_verified_extractor_with_literal_code() -> None:
    candidate: DynamicToken = _candidate("segredo")
    candidate.token_id = "t1"
    candidate.origin_step = 2

    extractor: Extractor = CandidateResolver._build_literal_extractor(candidate, AgentType.LITERAL)

    assert extractor.verified is True
    assert extractor.agent_type == AgentType.LITERAL
    assert "'segredo'" in extractor.code
