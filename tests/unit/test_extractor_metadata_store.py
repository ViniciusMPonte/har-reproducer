from pathlib import Path
from typing import Optional

from har_reproducer.fs_io.workspace import Workspace
from har_reproducer.models import AgentType, Extractor
from har_reproducer.reproduction.extractor_metadata_store import ExtractorMetadataStore


def test_load_returns_none_when_file_missing(tmp_path: Path) -> None:
    store: ExtractorMetadataStore = ExtractorMetadataStore(Workspace(tmp_path))

    result: Optional[Extractor] = store.load("naoexiste")

    assert result is None


def test_save_then_load_round_trips_extractor(tmp_path: Path) -> None:
    store: ExtractorMetadataStore = ExtractorMetadataStore(Workspace(tmp_path))
    extractor: Extractor = Extractor(token_id="t1", code="def f(r): pass", agent_type=AgentType.REGEX)

    store.save(extractor)
    loaded: Optional[Extractor] = store.load("t1")

    assert loaded == extractor


def test_load_returns_none_for_corrupted_json(tmp_path: Path) -> None:
    workspace: Workspace = Workspace(tmp_path)
    store: ExtractorMetadataStore = ExtractorMetadataStore(workspace)
    workspace.extractor_meta_file("t2").write_text("nao e json valido", encoding="utf-8")

    result: Optional[Extractor] = store.load("t2")

    assert result is None
