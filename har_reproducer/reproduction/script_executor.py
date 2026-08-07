import subprocess
import sys
from pathlib import Path
from subprocess import CompletedProcess
from typing import ClassVar, Dict, Optional

from har_reproducer.models import ScriptExecutionResult


class ScriptExecutor:
    TIMEOUT_RETURN_CODE: ClassVar[int] = -1

    def run(
            self,
            script_path: Path,
            timeout_seconds: float,
            env: Optional[Dict[str, str]] = None,
    ) -> ScriptExecutionResult:
        try:
            completed: CompletedProcess[str] = subprocess.run(
                [sys.executable, str(script_path)],
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return ScriptExecutionResult(
                timed_out=True, return_code=self.TIMEOUT_RETURN_CODE, stdout="", stderr=""
            )

        return ScriptExecutionResult(
            timed_out=False,
            return_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
