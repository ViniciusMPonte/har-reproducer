import re
from pathlib import Path
from re import Match, Pattern
from typing import ClassVar, List, Optional, Set, Tuple

from har_reproducer.fs_io import Workspace
from har_reproducer.replay.curl_dependency_parser import CurlDependencyParser


class ReplayRunner:
    STEP_FILENAME_PATTERN: ClassVar[Pattern[str]] = re.compile(r"req_(\d+)\.curl\.sh")

    def __init__(self, dependency_parser: CurlDependencyParser) -> None:
        self.dependency_parser: CurlDependencyParser = dependency_parser

    def _schedule_all(self) -> Tuple[List[int], Set[int]]:
        ordered_indexes: List[int] = self._existing_step_indexes()
        return ordered_indexes, set(ordered_indexes)

    def _schedule_slice(self, from_index: Optional[int], to_index: Optional[int]) -> Tuple[List[int], Set[int]]:
        existing: List[int] = self._existing_step_indexes()
        effective_from: int = from_index if from_index is not None else 0
        effective_to: int = to_index if to_index is not None else max(existing)
        ordered_indexes: List[int] = list(range(effective_from, effective_to + 1))
        return ordered_indexes, set(ordered_indexes)

    def _schedule_smart(self, from_index: Optional[int], to_index: Optional[int]) -> Tuple[List[int], Set[int]]:
        existing: List[int] = self._existing_step_indexes()
        floor: int = from_index if from_index is not None else 0
        target: int = to_index if to_index is not None else max(existing)

        schedule: Set[int] = {target}
        pending: Set[int] = {target}
        while pending:
            current: int = pending.pop()
            self._expand_pending(current, floor, schedule, pending)

        return sorted(schedule), schedule

    def _expand_pending(self, current: int, floor: int, schedule: Set[int], pending: Set[int]) -> None:
        curl_text: str = Workspace.curl_file(current).read_text(encoding="utf-8")
        dependencies = self.dependency_parser.parse(curl_text)
        for origin_step in dependencies.values():
            if origin_step >= floor and origin_step not in schedule:
                schedule.add(origin_step)
                pending.add(origin_step)

    def _schedule_list(self, steps_file: Path) -> Tuple[List[int], Set[int]]:
        lines: List[str] = steps_file.read_text(encoding="utf-8").splitlines()
        ordered_indexes: List[int] = [int(line.strip()) for line in lines if line.strip()]
        return ordered_indexes, set(ordered_indexes)

    def _existing_step_indexes(self) -> List[int]:
        indexes: List[int] = []
        for path in Workspace.curls.glob("req_*.curl.sh"):
            match: Optional[Match[str]] = self.STEP_FILENAME_PATTERN.match(path.name)
            if match is not None:
                indexes.append(int(match.group(1)))
        return sorted(indexes)
