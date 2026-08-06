import re
import shutil
from pathlib import Path
from typing import ClassVar, List, Optional, Pattern

from tests.support.cli_invocation_result import CliInvocationResult
from tests.support.cli_invoker import CliInvoker


class ReplayScenario:

    MITM_CAPTURE_DIR_NAME: ClassVar[str] = "mitm_capture"
    STEP_COMPLETED_PATTERN: ClassVar[Pattern[str]] = re.compile(r"^Step (\d+) completed with status", re.MULTILINE)

    def __init__(self, cli_invoker: CliInvoker, source_workspace: Path, tmp_path: Path) -> None:
        self.cli_invoker: CliInvoker = cli_invoker
        self.workspace: Path = tmp_path / "ws"
        shutil.copytree(source_workspace, self.workspace)
        self._reset_mitm_capture()
        self._rewrite_stale_absolute_paths(source_workspace)

    def run(self, mode_args: List[str], config_path: Optional[Path] = None) -> CliInvocationResult:
        argv: List[str] = ["replay", "--output", str(self.workspace), *mode_args]
        if config_path is not None:
            argv.extend(["--config", str(config_path)])
        return self.cli_invoker.invoke(argv)

    def executed_steps(self, stdout: str) -> List[int]:
        return [int(match.group(1)) for match in self.STEP_COMPLETED_PATTERN.finditer(stdout)]

    def replay_run_dirs(self) -> List[Path]:
        return list((self.workspace / "replays").iterdir())

    def _reset_mitm_capture(self) -> None:
        mitm_capture_dir: Path = self.workspace / self.MITM_CAPTURE_DIR_NAME
        shutil.rmtree(mitm_capture_dir)
        mitm_capture_dir.mkdir()

    def _rewrite_stale_absolute_paths(self, source_workspace: Path) -> None:
        old_prefix: str = str(source_workspace)
        new_prefix: str = str(self.workspace)
        for meta_file in self.workspace.joinpath("extractors").glob("*.meta.json"):
            self._rewrite_meta_file(meta_file, old_prefix, new_prefix)

    def _rewrite_meta_file(self, meta_file: Path, old_prefix: str, new_prefix: str) -> None:
        content: str = meta_file.read_text(encoding="utf-8")
        if old_prefix not in content:
            return
        meta_file.write_text(content.replace(old_prefix, new_prefix), encoding="utf-8")
