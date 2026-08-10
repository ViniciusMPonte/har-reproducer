import subprocess
from typing import List, Optional


class FakeProcess:

    def __init__(
            self,
            returncode: Optional[int] = None,
            wait_side_effects: Optional[List[Exception]] = None,
    ) -> None:
        self.returncode: Optional[int] = returncode
        self._wait_side_effects: List[Exception] = wait_side_effects or []
        self.terminate_calls: int = 0
        self.kill_calls: int = 0
        self.wait_calls: List[Optional[float]] = []

    def poll(self) -> Optional[int]:
        return self.returncode

    def terminate(self) -> None:
        self.terminate_calls += 1

    def kill(self) -> None:
        self.kill_calls += 1

    def wait(self, timeout: Optional[float] = None) -> int:
        self.wait_calls.append(timeout)
        if len(self.wait_calls) <= len(self._wait_side_effects):
            raise self._wait_side_effects[len(self.wait_calls) - 1]
        assert self.returncode is not None
        return self.returncode
