from pathlib import Path

from har_reproducer.models import AgentType, Extractor
from har_reproducer.replay.curl_dependency_parser import CurlDependencyParser
from har_reproducer.replay.replay_token_resolver import ReplayTokenResolver
from har_reproducer.session import SessionStore
from tests.support.fake_extractor_runner import FakeExtractorRunner
from tests.support.fake_metadata_store import FakeMetadataStore


def _resolver(extractor_runner: FakeExtractorRunner, metadata_store: FakeMetadataStore) -> ReplayTokenResolver:
    return ReplayTokenResolver(SessionStore(), extractor_runner, CurlDependencyParser(), metadata_store)


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


def test_resolve_one_returns_false_without_calling_record_observation_when_extractor_yields_none() -> None:
    metadata_store: FakeMetadataStore = FakeMetadataStore()
    extractor_runner: FakeExtractorRunner = FakeExtractorRunner(run_existing_result=None)
    resolver: ReplayTokenResolver = _resolver(extractor_runner, metadata_store)

    result: bool = resolver._resolve_one(
        "t1", {}, schedule=set(), replay_run_dir=Path("/replay"),
        res_refer_dir=Path("/refer"), original_responses_dir=Path("/original"),
    )

    assert result is False
    assert metadata_store.saved == {}
