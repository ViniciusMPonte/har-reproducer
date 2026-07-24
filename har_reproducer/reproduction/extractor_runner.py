import subprocess
import sys
from pathlib import Path
from subprocess import CompletedProcess
from typing import Any, ClassVar, Dict, Optional

from har_reproducer.fs_io import Workspace
from har_reproducer.models import Extractor
from har_reproducer.templates import ExtractorTemplate


class ExtractorRunner:
    EXTRACTOR_TIMEOUT_SECONDS: ClassVar[int] = 5

    def run(self, extractor: Extractor, response: Dict[str, Any]) -> Optional[str]:
        extractor_file: Path = self._write_extractor_script(extractor, response)
        self._cleanup_temp_file(extractor)
        return self._execute_extractor_script(extractor_file)

    def _write_extractor_script(self, extractor: Extractor, response: Dict[str, Any]) -> Path:
        extractor_file: Path = Workspace.extractor_file(extractor.token_id)
        wrapped_code: str = ExtractorTemplate.render_script(
            safe_token_id=extractor.token_id,
            code=extractor.code,
            response_sample=response,
        )
        extractor_file.write_text(wrapped_code, encoding="utf-8")
        return extractor_file

    def _cleanup_temp_file(self, extractor: Extractor) -> None:
        if not extractor.temp_file_path:
            return

        temp_file: Path = Path(extractor.temp_file_path)
        if temp_file.exists():
            temp_file.unlink()

    def _execute_extractor_script(self, extractor_file: Path) -> Optional[str]:
        try:
            result: CompletedProcess[str] = subprocess.run(
                [sys.executable, str(extractor_file)],
                capture_output=True,
                text=True,
                timeout=self.EXTRACTOR_TIMEOUT_SECONDS,
            )
        except Exception:
            return None

        if result.returncode != 0:
            return None
        return result.stdout.strip()
