import re
from typing import ClassVar, Dict, List, Optional, Pattern


class TokenFailureGuard:

    FAILURE_PATTERN: ClassVar[Pattern[str]] = re.compile(r"Failed to resolve token '([0-9a-f]+)' during replay:")
    STEP_COMPLETED_PATTERN: ClassVar[Pattern[str]] = re.compile(r"^Step (\d+) completed with status")

    def group_by_step(self, stdout: str) -> Dict[int, List[str]]:
        groups: Dict[int, List[str]] = {}
        pending: List[str] = []
        for line in stdout.splitlines():
            pending = self._collect_failure(line, pending)
            pending = self._flush_on_completion(line, pending, groups)
        return groups

    def assert_at_most_one_failure_per_step(self, stdout: str) -> None:
        violations: Dict[int, List[str]] = self._violations(self.group_by_step(stdout))
        if not violations:
            return
        raise AssertionError(self._violation_message(violations))

    def _collect_failure(self, line: str, pending: List[str]) -> List[str]:
        match: Optional[re.Match[str]] = self.FAILURE_PATTERN.search(line)
        if match is None:
            return pending
        return pending + [match.group(1)]

    def _flush_on_completion(self, line: str, pending: List[str], groups: Dict[int, List[str]]) -> List[str]:
        match: Optional[re.Match[str]] = self.STEP_COMPLETED_PATTERN.match(line)
        if match is None:
            return pending
        if pending:
            groups[int(match.group(1))] = pending
        return []

    def _violations(self, groups: Dict[int, List[str]]) -> Dict[int, List[str]]:
        return {step: ids for step, ids in groups.items() if len(ids) > 1}

    def _violation_message(self, violations: Dict[int, List[str]]) -> str:
        parts: List[str] = [f"step {step}: {ids}" for step, ids in sorted(violations.items())]
        return "Mais de um token falhou resolução no mesmo curl — " + "; ".join(parts)
