from pathlib import Path
from typing import List, Optional

from har_reproducer.fs_io.workspace import Workspace
from har_reproducer.models import AgentType, Extractor
from har_reproducer.reproduction.extractor_metadata_store import ExtractorMetadataStore, SilentExtractorMetadataStore


def _extractor(token_id: str) -> Extractor:
    return Extractor(token_id=token_id, code="return 1", agent_type=AgentType.REGEX, valid_count=3)


def test_list_all_returns_empty_list_when_no_meta_files(tmp_path: Path) -> None:
    workspace: Workspace = Workspace(tmp_path)

    extractors: List[Extractor] = ExtractorMetadataStore(workspace).list_all()

    assert extractors == []


def test_list_all_returns_all_valid_extractors_in_deterministic_order(tmp_path: Path) -> None:
    workspace: Workspace = Workspace(tmp_path)
    store: ExtractorMetadataStore = ExtractorMetadataStore(workspace)
    store.save(_extractor("bbbb"))
    store.save(_extractor("aaaa"))

    extractors: List[Extractor] = store.list_all()

    assert [extractor.token_id for extractor in extractors] == ["aaaa", "bbbb"]


def test_list_all_skips_corrupted_meta_file_without_raising(tmp_path: Path) -> None:
    workspace: Workspace = Workspace(tmp_path)
    store: ExtractorMetadataStore = ExtractorMetadataStore(workspace)
    store.save(_extractor("valid1"))
    corrupted_meta_file: Path = workspace.extractor_meta_file("corrupted")
    corrupted_meta_file.write_text("{not valid json", encoding="utf-8")

    extractors: List[Extractor] = store.list_all()

    assert [extractor.token_id for extractor in extractors] == ["valid1"]


def test_silent_store_load_returns_same_extractor_as_base_store(tmp_path: Path) -> None:
    workspace: Workspace = Workspace(tmp_path)
    ExtractorMetadataStore(workspace).save(_extractor("tok1"))

    base_loaded: Optional[Extractor] = ExtractorMetadataStore(workspace).load("tok1")
    silent_loaded: Optional[Extractor] = SilentExtractorMetadataStore(workspace).load("tok1")

    assert silent_loaded == base_loaded


def test_silent_store_save_does_not_create_meta_file(tmp_path: Path) -> None:
    workspace: Workspace = Workspace(tmp_path)
    meta_file: Path = workspace.extractor_meta_file("tok1")

    SilentExtractorMetadataStore(workspace).save(_extractor("tok1"))

    assert not meta_file.exists()


def test_silent_store_save_does_not_modify_existing_meta_file(tmp_path: Path) -> None:
    workspace: Workspace = Workspace(tmp_path)
    ExtractorMetadataStore(workspace).save(_extractor("tok1"))
    meta_file: Path = workspace.extractor_meta_file("tok1")
    before: str = meta_file.read_text(encoding="utf-8")

    SilentExtractorMetadataStore(workspace).save(_extractor("tok1", ))

    assert meta_file.read_text(encoding="utf-8") == before


def test_base_store_save_still_persists_to_disk(tmp_path: Path) -> None:
    workspace: Workspace = Workspace(tmp_path)
    meta_file: Path = workspace.extractor_meta_file("tok1")

    ExtractorMetadataStore(workspace).save(_extractor("tok1"))

    assert meta_file.exists()
