from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Union

from har_reproducer.models import ScriptExecutionResult
from har_reproducer.reproduction.script_executor import ScriptExecutor


class RecordedScriptExecutorCall(NamedTuple):
    script_path: Path
    timeout_seconds: float
    env: Optional[Dict[str, str]]


class FakeScriptExecutor(ScriptExecutor):

    def __init__(self, results: List[Union[ScriptExecutionResult, Exception]]) -> None:
        self.results: List[Union[ScriptExecutionResult, Exception]] = results
        self.calls: List[RecordedScriptExecutorCall] = []

    def run(
            self,
            script_path: Path,
            timeout_seconds: float,
            env: Optional[Dict[str, str]] = None,
    ) -> ScriptExecutionResult:
        self.calls.append(RecordedScriptExecutorCall(script_path, timeout_seconds, env))
        result: Union[ScriptExecutionResult, Exception] = self.results[len(self.calls) - 1]
        if isinstance(result, Exception):
            raise result
        return result
