import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from har_reproducer.agents.construction.agent_factory import AgentFactory
from har_reproducer.fs_io.workspace import Workspace
from har_reproducer.models import (
    AgentType,
    DynamicToken,
    Extractor,
    OriginContainer,
    ScriptExecutionResult,
    TokenLocation,
)
from har_reproducer.session import SessionStore
from har_reproducer.tracking.candidate_resolver import CandidateResolver, SlotStatus
from har_reproducer.tracking.response_corpus import ResponseCorpus
from tests.support.fake_extractor_runner import FakeExtractorRunner
from tests.support.fake_metadata_store import FakeMetadataStore
from tests.support.fake_script_executor import FakeScriptExecutor
from tests.support.fake_sleeper import FakeSleeper
from tests.support.recording_origin_finder import RecordingOriginFinder


class CandidateResolverFixture:
    STEP_INDEX_WIDTH: int = 4


def _candidate(current_value: str) -> DynamicToken:
    return DynamicToken(
        token_id="placeholder",
        path="header:X",
        current_value=current_value,
        destination_location=TokenLocation.HEADER,
        status="UnderReview",
    )


def _write_response(directory: Path, index: int, payload: Dict[str, Any]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    path: Path = directory / f"res_{index:0{CandidateResolverFixture.STEP_INDEX_WIDTH}d}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")


def _resolver(
        tmp_path: Path,
        extractor_runner: FakeExtractorRunner,
        metadata_store: FakeMetadataStore,
) -> CandidateResolver:
    return _resolver_with_executor(tmp_path, extractor_runner, metadata_store, FakeScriptExecutor([]))


def _resolver_verifying(tmp_path: Path, extracted_value: str, verifications: int) -> CandidateResolver:
    results: List[ScriptExecutionResult] = [
        ScriptExecutionResult(timed_out=False, return_code=0, stdout=extracted_value, stderr="")
        for _ in range(verifications)
    ]
    return _resolver_with_executor(
        tmp_path, FakeExtractorRunner(), FakeMetadataStore(), FakeScriptExecutor(list(results))
    )


def _resolver_with_executor(
        tmp_path: Path,
        extractor_runner: FakeExtractorRunner,
        metadata_store: FakeMetadataStore,
        script_executor: FakeScriptExecutor,
) -> CandidateResolver:
    workspace: Workspace = Workspace(tmp_path)
    agent_factory: AgentFactory = AgentFactory(workspace, script_executor, FakeSleeper(), None)
    corpus: ResponseCorpus = ResponseCorpus(tmp_path, CandidateResolverFixture.STEP_INDEX_WIDTH)
    return CandidateResolver(
        corpus, RecordingOriginFinder(corpus), SessionStore(), extractor_runner, metadata_store, agent_factory
    )


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


def test_process_candidate_records_origin_key_and_container_from_header(tmp_path: Path) -> None:
    _write_response(tmp_path, 1, {"headers": {"ETag": 'W/"9b1-abc"'}})
    resolver: CandidateResolver = _resolver_verifying(tmp_path, 'W/"9b1-abc"', 1)

    resolved: List[DynamicToken] = resolver.resolve([_candidate('W/"9b1-abc"')], 5)

    assert resolved[0].origin_step == 1
    assert resolved[0].origin_key == "ETag"
    assert resolved[0].origin_container is OriginContainer.HEADER


def test_process_candidate_without_origin_leaves_the_three_fields_none(tmp_path: Path) -> None:
    _write_response(tmp_path, 1, {"headers": {"ETag": "outro"}})
    resolver: CandidateResolver = _resolver(tmp_path, FakeExtractorRunner(), FakeMetadataStore())

    resolved: List[DynamicToken] = resolver.resolve([_candidate("inexistente")], 5)

    assert resolved[0].status == "NotFound"
    assert resolved[0].origin_step is None
    assert resolved[0].origin_key is None
    assert resolved[0].origin_container is None


def test_process_candidate_matching_in_body_has_no_origin_key(tmp_path: Path) -> None:
    _write_response(tmp_path, 1, {"body": '{"token":"abc123"}'})
    resolver: CandidateResolver = _resolver_verifying(tmp_path, "abc123", 1)

    resolved: List[DynamicToken] = resolver.resolve([_candidate("abc123")], 5)

    assert resolved[0].origin_step == 1
    assert resolved[0].origin_key is None
    assert resolved[0].origin_container is None


def test_negative_cache_narrows_the_search_window_on_the_next_lookup(tmp_path: Path) -> None:
    _write_response(tmp_path, 0, {"body": "nada aqui"})
    resolver: CandidateResolver = _resolver(tmp_path, FakeExtractorRunner(), FakeMetadataStore())
    finder: RecordingOriginFinder = resolver.origin_finder

    resolver.resolve([_candidate("ausente")], 5)
    resolver.resolve([_candidate("ausente")], 9)

    assert [call.from_step_index for call in finder.find_calls] == [0, 5]
    assert [call.before_step_index for call in finder.find_calls] == [5, 9]


def test_negative_cache_does_not_hide_an_origin_written_later(tmp_path: Path) -> None:
    _write_response(tmp_path, 0, {"body": "nada aqui"})
    resolver: CandidateResolver = _resolver_verifying(tmp_path, "segredo", 1)

    first: List[DynamicToken] = resolver.resolve([_candidate("segredo")], 5)
    assert first[0].status == "NotFound"

    _write_response(tmp_path, 6, {"headers": {"X-Token": "segredo"}})

    second: List[DynamicToken] = resolver.resolve([_candidate("segredo")], 9)

    assert second[0].origin_step == 6
    assert second[0].origin_key == "X-Token"


def test_positive_cache_keeps_a_single_find_call(tmp_path: Path) -> None:
    _write_response(tmp_path, 1, {"headers": {"X-Token": "segredo"}})
    resolver: CandidateResolver = _resolver_verifying(tmp_path, "segredo", 2)
    finder: RecordingOriginFinder = resolver.origin_finder

    resolver.resolve([_candidate("segredo")], 5)
    resolver.resolve([_candidate("segredo")], 9)

    assert len(finder.find_calls) == 1


def test_generate_new_extractor_reads_the_response_from_the_corpus(tmp_path: Path) -> None:
    _write_response(tmp_path, 1, {"headers": {"X-Token": "segredo"}})
    resolver: CandidateResolver = _resolver_verifying(tmp_path, "segredo", 1)

    resolved: List[DynamicToken] = resolver.resolve([_candidate("segredo")], 5)

    assert resolved[0].origin_location is TokenLocation.HEADER


def test_check_persisted_slot_runs_existing_extractor_over_the_corpus_directory(tmp_path: Path) -> None:
    metadata_store: FakeMetadataStore = FakeMetadataStore()
    metadata_store.save(Extractor(token_id="t1", code="def f(r): pass", agent_type=AgentType.REGEX))
    extractor_runner: FakeExtractorRunner = FakeExtractorRunner(run_existing_result="v1")
    resolver: CandidateResolver = _resolver(tmp_path, extractor_runner, metadata_store)

    resolver._check_persisted_slot("t1", _candidate("v1"))

    assert extractor_runner.run_existing_calls[0].response_override_dir == tmp_path
