from pathlib import Path
from typing import Optional, Set, Tuple

import pytest

from har_reproducer.models import AgentType, Extractor, TokenResolutionStatus
from har_reproducer.replay.curl_token_comment import CurlTokenComment, ReplayStatusPhrase
from har_reproducer.replay.replay_token_resolver import ReplayTokenResolver
from har_reproducer.session import SessionStore
from tests.support.fake_extractor_runner import FakeExtractorRunner, RecordedRunCall
from tests.support.fake_metadata_store import FakeMetadataStore

_CURL_TOKEN_COMMENT: CurlTokenComment = CurlTokenComment(step_index_width=4)


def _resolver(extractor_runner: FakeExtractorRunner, metadata_store: FakeMetadataStore) -> ReplayTokenResolver:
    return ReplayTokenResolver(SessionStore(), extractor_runner, _CURL_TOKEN_COMMENT, metadata_store)


def test_reference_dir_for_step_without_origin_uses_refer_dir(tmp_path: Path) -> None:
    res_refer_dir: Path = tmp_path / "refer"
    original_dir: Path = tmp_path / "original"

    result: Path = ReplayTokenResolver._reference_dir_for_step(None, res_refer_dir, original_dir)

    assert result == res_refer_dir


def test_reference_dir_for_step_prefers_refer_dir_when_file_exists(tmp_path: Path) -> None:
    res_refer_dir: Path = tmp_path / "refer"
    original_dir: Path = tmp_path / "original"
    res_refer_dir.mkdir()
    (res_refer_dir / "res_0002.json").write_text("{}", encoding="utf-8")

    result: Path = ReplayTokenResolver._reference_dir_for_step(2, res_refer_dir, original_dir)

    assert result == res_refer_dir


def test_reference_dir_for_step_falls_back_to_original_dir_when_missing(tmp_path: Path) -> None:
    res_refer_dir: Path = tmp_path / "refer"
    original_dir: Path = tmp_path / "original"
    res_refer_dir.mkdir()

    result: Path = ReplayTokenResolver._reference_dir_for_step(2, res_refer_dir, original_dir)

    assert result == original_dir


def test_record_observation_reaches_static_threshold() -> None:
    metadata_store: FakeMetadataStore = FakeMetadataStore()
    metadata_store.save(
        Extractor(
            token_id="t1", code="def f(r): pass", agent_type=AgentType.REGEX,
            valid_count=4, last_value="v", ever_changed=False,
        )
    )
    resolver: ReplayTokenResolver = _resolver(FakeExtractorRunner(), metadata_store)

    result: bool = resolver._record_observation("t1", "v")

    assert result is True
    assert metadata_store.load("t1").valid_count == 5


def test_record_observation_marks_ever_changed_on_divergent_value() -> None:
    metadata_store: FakeMetadataStore = FakeMetadataStore()
    metadata_store.save(
        Extractor(
            token_id="t1", code="def f(r): pass", agent_type=AgentType.REGEX,
            valid_count=4, last_value="v", ever_changed=False,
        )
    )
    resolver: ReplayTokenResolver = _resolver(FakeExtractorRunner(), metadata_store)

    result: bool = resolver._record_observation("t1", "outro")

    assert result is False
    assert metadata_store.load("t1").ever_changed is True


def test_record_observation_never_returns_true_again_after_ever_changed() -> None:
    metadata_store: FakeMetadataStore = FakeMetadataStore()
    metadata_store.save(
        Extractor(
            token_id="t1", code="def f(r): pass", agent_type=AgentType.REGEX,
            valid_count=10, last_value="v", ever_changed=True,
        )
    )
    resolver: ReplayTokenResolver = _resolver(FakeExtractorRunner(), metadata_store)

    result: bool = resolver._record_observation("t1", "v")

    assert result is False


def test_resolve_one_returns_unresolved_without_calling_record_observation_when_extractor_yields_none() -> None:
    metadata_store: FakeMetadataStore = FakeMetadataStore()
    extractor_runner: FakeExtractorRunner = FakeExtractorRunner(run_existing_result=None)
    resolver: ReplayTokenResolver = _resolver(extractor_runner, metadata_store)

    result: TokenResolutionStatus = resolver._resolve_one(
        "t1", {}, schedule=set(), replay_run_dir=Path("/replay"),
        res_refer_dir=Path("/refer"), original_responses_dir=Path("/original"),
    )

    assert result == TokenResolutionStatus.UNRESOLVED
    assert metadata_store.saved == {}


def test_fallback_to_captured_uses_captured_value_when_extractor_yields_none() -> None:
    metadata_store: FakeMetadataStore = FakeMetadataStore()
    metadata_store.save(
        Extractor(token_id="t1", code="def f(r): pass", agent_type=AgentType.REGEX, captured_value="capturado")
    )
    extractor_runner: FakeExtractorRunner = FakeExtractorRunner(run_existing_result=None)
    resolver: ReplayTokenResolver = _resolver(extractor_runner, metadata_store)

    result: TokenResolutionStatus = resolver._resolve_one(
        "t1", {}, schedule=set(), replay_run_dir=Path("/replay"),
        res_refer_dir=Path("/refer"), original_responses_dir=Path("/original"),
    )

    assert result == TokenResolutionStatus.CAPTURED_FALLBACK
    assert resolver.session_store.state.tokens["t1"] == "capturado"


def test_fallback_to_captured_does_not_record_observation() -> None:
    metadata_store: FakeMetadataStore = FakeMetadataStore()
    metadata_store.save(
        Extractor(
            token_id="t1", code="def f(r): pass", agent_type=AgentType.REGEX,
            captured_value="capturado", valid_count=2, last_value="v", ever_changed=False,
        )
    )
    extractor_runner: FakeExtractorRunner = FakeExtractorRunner(run_existing_result=None)
    resolver: ReplayTokenResolver = _resolver(extractor_runner, metadata_store)

    result: TokenResolutionStatus = resolver._resolve_one(
        "t1", {}, schedule=set(), replay_run_dir=Path("/replay"),
        res_refer_dir=Path("/refer"), original_responses_dir=Path("/original"),
    )

    assert result == TokenResolutionStatus.CAPTURED_FALLBACK
    stored: Optional[Extractor] = metadata_store.load("t1")
    assert stored is not None
    assert stored.valid_count == 2
    assert stored.last_value == "v"
    assert stored.ever_changed is False


def test_fallback_to_captured_unresolved_without_captured_value(capsys: pytest.CaptureFixture[str]) -> None:
    metadata_store: FakeMetadataStore = FakeMetadataStore()
    extractor_runner: FakeExtractorRunner = FakeExtractorRunner(run_existing_result=None)
    resolver: ReplayTokenResolver = _resolver(extractor_runner, metadata_store)

    result: TokenResolutionStatus = resolver._resolve_one(
        "t1", {}, schedule=set(), replay_run_dir=Path("/replay"),
        res_refer_dir=Path("/refer"), original_responses_dir=Path("/original"),
    )

    assert result == TokenResolutionStatus.UNRESOLVED
    assert "Failed to resolve token 't1' during replay:" in capsys.readouterr().out


def test_resolve_returns_static_and_fallback_sets() -> None:
    metadata_store: FakeMetadataStore = FakeMetadataStore()
    metadata_store.save(
        Extractor(
            token_id="aaa", code="def f(r): pass", agent_type=AgentType.REGEX,
            valid_count=4, last_value="v", ever_changed=False,
        )
    )
    metadata_store.save(
        Extractor(token_id="bbb", code="def f(r): pass", agent_type=AgentType.REGEX, captured_value="capturado")
    )
    extractor_runner: FakeExtractorRunner = FakeExtractorRunner(
        run_existing_by_token={"aaa": "v", "bbb": None}
    )
    resolver: ReplayTokenResolver = _resolver(extractor_runner, metadata_store)
    curl_text: str = "curl -X GET 'https://x?t={{extractor:aaa}}&u={{extractor:bbb}}'"

    static_ids: Set[str]
    fallback_ids: Set[str]
    static_ids, fallback_ids = resolver.resolve(
        curl_text, schedule=set(), replay_run_dir=Path("/replay"),
        res_refer_dir=Path("/refer"), original_responses_dir=Path("/original"),
    )

    assert static_ids == {"aaa"}
    assert fallback_ids == {"bbb"}


def test_resolve_recovers_origin_step_after_curl_text_annotated_with_replay_status() -> None:
    metadata_store: FakeMetadataStore = FakeMetadataStore()
    extractor_runner: FakeExtractorRunner = FakeExtractorRunner(run_existing_result="v")
    resolver: ReplayTokenResolver = _resolver(extractor_runner, metadata_store)
    line: str = _CURL_TOKEN_COMMENT.with_replay_status(
        _CURL_TOKEN_COMMENT.format_dependency_line("aaa", 3), ReplayStatusPhrase.PROBABLY_STATIC
    )
    curl_text: str = f"{line}\ncurl -X GET 'https://x?t={{{{extractor:aaa}}}}'"

    static_ids: Set[str]
    fallback_ids: Set[str]
    static_ids, fallback_ids = resolver.resolve(
        curl_text, schedule=set(), replay_run_dir=Path("/replay"),
        res_refer_dir=Path("/refer"), original_responses_dir=Path("/original"),
    )

    assert extractor_runner.run_existing_calls == [RecordedRunCall("aaa", Path("/original"))]
    assert static_ids == set()
    assert fallback_ids == set()


def test_resolve_one_passes_original_dir_as_override_when_origin_outside_schedule() -> None:
    extractor_runner: FakeExtractorRunner = FakeExtractorRunner(run_existing_result="v")
    resolver: ReplayTokenResolver = _resolver(extractor_runner, FakeMetadataStore())

    status: TokenResolutionStatus = resolver._resolve_one(
        "t1", {"t1": 3}, schedule={4}, replay_run_dir=Path("/replay"),
        res_refer_dir=Path("/refer"), original_responses_dir=Path("/original"),
    )

    assert status == TokenResolutionStatus.RESOLVED
    assert extractor_runner.run_existing_calls == [RecordedRunCall("t1", Path("/original"))]
