from pathlib import Path
from typing import Optional

from har_reproducer.fs_io.workspace_dir import WorkspaceDir


class Workspace:
    _output_dir: Optional[Path] = None

    curls: Path
    real_responses: Path
    real_requests: Path
    extractors: Path
    temp_extractors: Path
    mitm_capture: Path

    @classmethod
    def init(cls, output_dir: Path) -> None:
        cls._output_dir = Path(output_dir)
        cls._output_dir.mkdir(parents=True, exist_ok=True)
        for workspace_dir in WorkspaceDir:
            path: Path = cls._output_dir / workspace_dir.value
            path.mkdir(parents=True, exist_ok=True)
            setattr(cls, workspace_dir.value, path)

    @classmethod
    def _ensure_initialized(cls) -> None:
        if cls._output_dir is None:
            raise RuntimeError(
                "Workspace não inicializado. Chame Workspace.init(output_dir) primeiro."
            )

    @classmethod
    def temp_extractor_file(cls, safe_token_id: str) -> Path:
        cls._ensure_initialized()
        return cls.temp_extractors / f"temp_extractor_{safe_token_id}.py"

    @classmethod
    def extractor_file(cls, safe_token_id: str) -> Path:
        cls._ensure_initialized()
        return cls.extractors / f"extract_{safe_token_id}.py"

    @classmethod
    def request_file(cls, index: int) -> Path:
        cls._ensure_initialized()
        return cls.real_requests / f"req_{index:04d}.json"

    @classmethod
    def response_file(cls, index: int) -> Path:
        cls._ensure_initialized()
        return cls.real_responses / f"res_{index:04d}.json"

    @classmethod
    def mitm_capture_file(cls) -> Path:
        cls._ensure_initialized()
        return cls.mitm_capture / "capture.har"

    @classmethod
    def curl_file(cls, index: int) -> Path:
        cls._ensure_initialized()
        return cls.curls / f"req_{index:04d}.curl.sh"
