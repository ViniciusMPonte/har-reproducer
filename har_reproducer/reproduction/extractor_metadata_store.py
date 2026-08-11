from pathlib import Path
from typing import Optional

from har_reproducer.fs_io import Workspace
from har_reproducer.models import Extractor


class ExtractorMetadataStore:
    def __init__(self, workspace: Workspace) -> None:
        self.workspace: Workspace = workspace

    def load(self, token_id: str) -> Optional[Extractor]:
        meta_file: Path = self.workspace.extractor_meta_file(token_id)
        if not meta_file.exists():
            return None
        try:
            return Extractor.model_validate_json(meta_file.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[AVISO] Falha ao carregar metadado do extractor '{token_id}': {e}")
            return None

    def save(self, extractor: Extractor) -> None:
        meta_file: Path = self.workspace.extractor_meta_file(extractor.token_id)
        meta_file.write_text(extractor.model_dump_json(indent=2), encoding="utf-8")


class SilentExtractorMetadataStore(ExtractorMetadataStore):
    def save(self, extractor: Extractor) -> None:
        return None
