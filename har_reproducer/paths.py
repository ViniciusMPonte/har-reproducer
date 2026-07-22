from pathlib import Path
from typing import Optional, Tuple


class Workspace:

    _output_dir: Optional[Path] = None

    curls: Path
    real_responses: Path
    real_requests: Path
    extractors: Path
    temp_extractors: Path

    _SUBDIRS: Tuple[str, ...] = (
        "curls",
        "real_responses",
        "real_requests",
        "extractors",
        "temp_extractors",
    )

    @classmethod
    def init(cls, output_dir: Path) -> None:
        cls._output_dir = Path(output_dir)
        cls._output_dir.mkdir(parents=True, exist_ok=True)
        for name in cls._SUBDIRS:
            path: Path = cls._output_dir / name
            path.mkdir(parents=True, exist_ok=True)
            setattr(cls, name, path)

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
