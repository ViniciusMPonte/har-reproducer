import re
from pathlib import Path
from re import Match, Pattern
from typing import ClassVar, List, Optional, Set, Tuple

from har_reproducer.fs_io import Workspace
from har_reproducer.models import StepResponse
from har_reproducer.replay.curl_dependency_parser import CurlDependencyParser
from har_reproducer.replay.replay_result_comparator import ReplayResultComparator
from har_reproducer.replay.replay_token_resolver import ReplayTokenResolver
from har_reproducer.reproduction import CurlHttpTransport, StepRetryPolicy
from har_reproducer.session.session_store import SessionStore


class ReplayRunner:
    STEP_FILENAME_PATTERN: ClassVar[Pattern[str]] = re.compile(r"req_(\d+)\.curl\.sh")
    STATIC_WARNING_SUFFIX: ClassVar[str] = " - probably static"

    def __init__(
            self,
            dependency_parser: CurlDependencyParser,
            session_store: SessionStore,
            http_transport: CurlHttpTransport,
            replay_token_resolver: ReplayTokenResolver,
            retry_policy: StepRetryPolicy,
            comparator: ReplayResultComparator,
            run_id: str,
            replay_run_dir: Path,
            res_refer_dir: Path,
            original_responses_dir: Path,
    ) -> None:
        self.dependency_parser: CurlDependencyParser = dependency_parser
        self.session_store: SessionStore = session_store
        self.http_transport: CurlHttpTransport = http_transport
        self.replay_token_resolver: ReplayTokenResolver = replay_token_resolver
        self.retry_policy: StepRetryPolicy = retry_policy
        self.comparator: ReplayResultComparator = comparator
        self.run_id: str = run_id
        self.replay_run_dir: Path = replay_run_dir
        self.res_refer_dir: Path = res_refer_dir
        self.original_responses_dir: Path = original_responses_dir

    def run_all(self) -> bool:
        ordered_indexes, schedule = self._schedule_all()
        return self._run_schedule(ordered_indexes, schedule)

    def run_slice(self, from_index: Optional[int], to_index: Optional[int]) -> bool:
        ordered_indexes, schedule = self._schedule_slice(from_index, to_index)
        return self._run_schedule(ordered_indexes, schedule)

    def run_smart(self, from_index: Optional[int], to_index: Optional[int]) -> bool:
        ordered_indexes, schedule = self._schedule_smart(from_index, to_index)
        return self._run_schedule(ordered_indexes, schedule)

    def run_list(self, steps_file: Path) -> bool:
        ordered_indexes, schedule = self._schedule_list(steps_file)
        return self._run_schedule(ordered_indexes, schedule)

    def _run_schedule(self, ordered_indexes: List[int], schedule: Set[int]) -> bool:
        if not ordered_indexes:
            raise ValueError("ReplayRunner: schedule vazio — nenhum step para processar.")

        last_index: int = ordered_indexes[0]
        last_response: StepResponse = self._run_step(last_index, schedule)
        for index in ordered_indexes[1:]:
            last_response = self._run_step(index, schedule)
            last_index = index

        is_match: bool = self.comparator.matches_original(last_index, last_response)
        print(
            f"\nReplay Validation Result: {'✓ SUCCESS' if is_match else '✗ MISMATCH'} "
            f"(step {last_index} status code vs. original)"
        )
        return is_match

    def _run_step(self, index: int, schedule: Set[int]) -> StepResponse:
        curl_text: str = Workspace.curl_file(index).read_text(encoding="utf-8")

        def attempt() -> StepResponse:
            static_token_ids: Set[str] = self.replay_token_resolver.resolve(
                curl_text, schedule, self.replay_run_dir, self.res_refer_dir, self.original_responses_dir
            )
            if static_token_ids:
                self._annotate_static_tokens(index, static_token_ids)
            curl_resolved: str = self.session_store.render(curl_text)
            return self.http_transport.send_request(curl_resolved, index)

        def recover(response: StepResponse) -> bool:
            if response.status_code not in StepRetryPolicy.RECOVERABLE_STATUS_CODES:
                return False
            print(f"Detected {response.status_code}. Attempting deterministic recovery (token refresh)...")
            return True

        response: StepResponse = self.retry_policy.execute(index, attempt, recover)
        Workspace.replay_response_file(self.run_id, index).write_text(
            response.model_dump_json(indent=2), encoding="utf-8"
        )
        print(f"Step {index} completed with status {response.status_code}")
        return response

    def _annotate_static_tokens(self, index: int, token_ids: Set[str]) -> None:
        curl_file: Path = Workspace.curl_file(index)
        text: str = curl_file.read_text(encoding="utf-8")
        updated: str = text
        for token_id in token_ids:
            updated = self._mark_token_static(updated, token_id)
        if updated != text:
            curl_file.write_text(updated, encoding="utf-8")

    @classmethod
    def _mark_token_static(cls, text: str, token_id: str) -> str:
        prefix: str = f"# Token {token_id} comes from response of step "
        lines: List[str] = text.splitlines()
        for i, line in enumerate(lines):
            if line.startswith(prefix) and not line.endswith(cls.STATIC_WARNING_SUFFIX):
                lines[i] = line + cls.STATIC_WARNING_SUFFIX
                break
        return "\n".join(lines) + "\n"

    def _schedule_all(self) -> Tuple[List[int], Set[int]]:
        ordered_indexes: List[int] = self._existing_step_indexes()
        return ordered_indexes, set(ordered_indexes)

    def _schedule_slice(self, from_index: Optional[int], to_index: Optional[int]) -> Tuple[List[int], Set[int]]:
        existing: List[int] = self._existing_step_indexes()
        effective_from: int = from_index if from_index is not None else 0
        effective_to: int = to_index if to_index is not None else max(existing)
        ordered_indexes: List[int] = [index for index in existing if effective_from <= index <= effective_to]
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
