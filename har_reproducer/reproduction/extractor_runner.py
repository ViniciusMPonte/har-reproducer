import os
from pathlib import Path
from typing import ClassVar, Dict, Optional

from har_reproducer.fs_io import Workspace
from har_reproducer.models import Extractor, ScriptExecutionResult
from har_reproducer.reproduction.script_executor import ScriptExecutor
from har_reproducer.templates import ExtractorTemplate, IdentifierSanitizer


class ExtractorRunner:
    EXTRACTOR_TIMEOUT_SECONDS: ClassVar[int] = 5

    def __init__(self, script_executor: ScriptExecutor) -> None:
        self.script_executor: ScriptExecutor = script_executor

    def run(self, extractor: Extractor, response_override_dir: Optional[Path] = None) -> Optional[str]:
        extractor_file: Path = self._write_extractor_script(extractor)
        self._cleanup_temp_file(extractor)
        return self._execute_extractor_script(extractor_file, response_override_dir)

    def run_existing(
            self,
            token_id: str,
            response_override_dir: Optional[Path] = None,
    ) -> Optional[str]:
        extractor_file: Path = Workspace.extractor_file(token_id)
        if not extractor_file.exists():
            return None
        return self._execute_extractor_script(extractor_file, response_override_dir)

    def _write_extractor_script(self, extractor: Extractor) -> Path:
        if extractor.origin_step is None:
            raise ValueError(f"Extractor '{extractor.token_id}' has no origin_step to load a response from.")

        extractor_file: Path = Workspace.extractor_file(extractor.token_id)
        wrapped_code: str = ExtractorTemplate.render_script(
            safe_token_id=IdentifierSanitizer.sanitize(extractor.token_id),
            code=extractor.code,
            step_index=extractor.origin_step,
        )
        extractor_file.write_text(wrapped_code, encoding="utf-8")
        return extractor_file

    def _cleanup_temp_file(self, extractor: Extractor) -> None:
        if not extractor.temp_file_path:
            return

        temp_file: Path = Path(extractor.temp_file_path)
        if temp_file.exists():
            temp_file.unlink()

    def _execute_extractor_script(
            self,
            extractor_file: Path,
            response_override_dir: Optional[Path] = None,
    ) -> Optional[str]:
        env: Dict[str, str] = self._build_env(response_override_dir)
        try:
            result: ScriptExecutionResult = self.script_executor.run(
                extractor_file, self.EXTRACTOR_TIMEOUT_SECONDS, env
            )
        except Exception:
            return None

        if result.return_code != 0:
            return None
        return result.stdout.strip()

    @staticmethod
    def _build_env(response_override_dir: Optional[Path]) -> Dict[str, str]:
        env: Dict[str, str] = dict(os.environ)
        if response_override_dir is not None:
            env["HAR_REPRODUCER_RESPONSE_OVERRIDE_DIR"] = str(response_override_dir)
        return env
