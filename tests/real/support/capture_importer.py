import shutil
from datetime import date
from pathlib import Path
from typing import ClassVar, Tuple


class CaptureImporter:

    SUBDIRECTORIES: ClassVar[Tuple[str, ...]] = ("real_requests", "real_responses", "original_responses")

    def __init__(self, captures_root: Path) -> None:
        self.captures_root: Path = captures_root

    def import_capture(self, workspace_output_dir: Path, domain: str, captured_on: date) -> Path:
        destination: Path = self.captures_root / f"{domain}__{captured_on:%Y%m%d}"
        for subdirectory in self.SUBDIRECTORIES:
            shutil.copytree(
                workspace_output_dir / subdirectory, destination / subdirectory, dirs_exist_ok=True
            )
        return destination
