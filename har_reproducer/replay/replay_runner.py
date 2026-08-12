import re
from pathlib import Path
from re import Match, Pattern
from typing import ClassVar, Dict, Iterable, List, Optional, Set, Tuple

from har_reproducer.contracts import HttpTransport
from har_reproducer.fs_io import Workspace
from har_reproducer.models import StepResponse
from har_reproducer.replay.curl_token_comment import CurlTokenComment, ReplayStatusPhrase
from har_reproducer.replay.replay_result_comparator import ReplayResultComparator
from har_reproducer.replay.replay_token_resolver import ReplayTokenResolver
from har_reproducer.reproduction import StepRetryPolicy
from har_reproducer.session.session_store import SessionStore


class ReplayRunner:
    STEP_FILENAME_PATTERN: ClassVar[Pattern[str]] = re.compile(r"req_(\d+)\.curl\.sh")

    def __init__(
            self,
            workspace: Workspace,
            curl_token_comment: CurlTokenComment,
            session_store: SessionStore,
            http_transport: HttpTransport,
            replay_token_resolver: ReplayTokenResolver,
            retry_policy: StepRetryPolicy,
            comparator: ReplayResultComparator,
            run_id: str,
            replay_run_dir: Path,
            res_refer_dir: Path,
            original_responses_dir: Path,
    ) -> None:
        self.workspace: Workspace = workspace
        self.curl_token_comment: CurlTokenComment = curl_token_comment
        self.session_store: SessionStore = session_store
        self.http_transport: HttpTransport = http_transport
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
        ordered_indexes, schedule = self.compute_smart_schedule(from_index, to_index)
        return self._run_schedule(ordered_indexes, schedule)

    def run_list(self, steps_file: Path) -> bool:
        ordered_indexes, schedule = self._schedule_list(steps_file)
        return self._run_schedule(ordered_indexes, schedule)

    def execute_schedule(
            self, ordered_indexes: List[int], schedule: Set[int], annotate: bool = True
    ) -> List[Tuple[int, StepResponse]]:
        if not ordered_indexes:
            raise ValueError("ReplayRunner: schedule vazio — nenhum step para processar.")
        return [(index, self._run_step(index, schedule, annotate)) for index in ordered_indexes]

    def _run_schedule(self, ordered_indexes: List[int], schedule: Set[int]) -> bool:
        results: List[Tuple[int, StepResponse, bool]] = [
            (index, response, self.comparator.matches_original(index, response))
            for index, response in self.execute_schedule(ordered_indexes, schedule)
        ]

        self._print_step_report(results)

        target_index: int = results[-1][0]
        target_matched: bool = results[-1][2]
        intermediate_broken: bool = any(response.status_code == 0 for _, response, _ in results[:-1])
        is_match: bool = target_matched and not intermediate_broken
        failed_steps: List[int] = [index for index, _, matched in results if not matched]

        print(
            f"\nReplay Validation Result: {'✓ SUCCESS' if is_match else '✗ FAILURE'}"
            f"{' (step ' + str(target_index) + ' status code vs. original)' if is_match else ' (steps diverged: ' + ', '.join(str(s) for s in failed_steps) + ')'}"
        )
        return is_match

    def _print_step_report(self, results: List[Tuple[int, StepResponse, bool]]) -> None:
        print("Replay step results:")
        for index, response, matched in results:
            original: Optional[int] = self.comparator.original_status_code(index)
            original_display: str = str(original) if original is not None else "?"
            verdict: str = "✓ matched" if matched else "✗ MISMATCH"
            print(f"  Step {index}: {verdict} ({response.status_code} vs original {original_display})")

    def _run_step(self, index: int, schedule: Set[int], annotate: bool = True) -> StepResponse:
        curl_text: str = self.workspace.curl_file(index).read_text(encoding="utf-8")

        def attempt() -> StepResponse:
            static_token_ids: Set[str]
            fallback_token_ids: Set[str]
            static_token_ids, fallback_token_ids = self.replay_token_resolver.resolve(
                curl_text, schedule, self.replay_run_dir, self.res_refer_dir, self.original_responses_dir
            )
            if annotate and static_token_ids:
                self._annotate_static_tokens(index, static_token_ids)
            if annotate and fallback_token_ids:
                self._annotate_fallback_tokens(index, fallback_token_ids)
            curl_resolved: str = self.session_store.render(curl_text)
            return self.http_transport.send_request(curl_resolved, index)

        def recover(response: StepResponse) -> bool:
            if response.status_code not in StepRetryPolicy.RECOVERABLE_STATUS_CODES:
                return False
            print(f"Detected {response.status_code}. Attempting deterministic recovery (token refresh)...")
            return True

        response: StepResponse = self.retry_policy.execute(index, attempt, recover)
        self.workspace.replay_response_file(self.run_id, index).write_text(
            response.model_dump_json(indent=2), encoding="utf-8"
        )
        print(f"Step {index} completed with status {response.status_code}")
        return response

    def _annotate_static_tokens(self, index: int, token_ids: Set[str]) -> None:
        self._annotate(index, token_ids, ReplayStatusPhrase.PROBABLY_STATIC)

    def _annotate_fallback_tokens(self, index: int, token_ids: Set[str]) -> None:
        self._annotate(index, token_ids, ReplayStatusPhrase.COULD_NOT_EXTRACT)

    def _annotate(self, index: int, token_ids: Set[str], phrase: ReplayStatusPhrase) -> None:
        curl_file: Path = self.workspace.curl_file(index)
        text: str = curl_file.read_text(encoding="utf-8")
        updated: str = text
        for token_id in token_ids:
            updated = self._apply_replay_status(updated, token_id, phrase)
        if updated != text:
            curl_file.write_text(updated, encoding="utf-8")

    def _apply_replay_status(self, text: str, token_id: str, phrase: ReplayStatusPhrase) -> str:
        prefix: str = f"# [Token {token_id} "
        lines: List[str] = text.splitlines()
        for i, line in enumerate(lines):
            if line.startswith(prefix):
                lines[i] = self.curl_token_comment.with_replay_status(line, phrase)
                break
        return "\n".join(lines) + "\n"

    def _schedule_all(self) -> Tuple[List[int], Set[int]]:
        ordered_indexes: List[int] = self.existing_step_indexes()
        return ordered_indexes, set(ordered_indexes)

    def _schedule_slice(self, from_index: Optional[int], to_index: Optional[int]) -> Tuple[List[int], Set[int]]:
        existing: List[int] = self.existing_step_indexes()
        effective_from: int = from_index if from_index is not None else 0
        effective_to: int = to_index if to_index is not None else max(existing)
        ordered_indexes: List[int] = [index for index in existing if effective_from <= index <= effective_to]
        return ordered_indexes, set(ordered_indexes)

    def compute_smart_schedule(self, from_index: Optional[int], to_index: Optional[int]) -> Tuple[List[int], Set[int]]:
        existing: List[int] = self.existing_step_indexes()
        existing_set: Set[int] = set(existing)
        floor: int = from_index if from_index is not None else 0
        target: int = to_index if to_index is not None else max(existing)
        self._require_all_existing({target}, existing_set)

        schedule: Set[int] = {target}
        pending: Set[int] = {target}
        while pending:
            current: int = pending.pop()
            self._expand_pending(current, floor, existing_set, schedule, pending)

        return sorted(schedule), schedule

    def _expand_pending(
            self, current: int, floor: int, existing_set: Set[int], schedule: Set[int], pending: Set[int]
    ) -> None:
        curl_text: str = self.workspace.curl_file(current).read_text(encoding="utf-8")
        dependencies: Dict[str, int] = self.curl_token_comment.parse(curl_text)
        for origin_step in dependencies.values():
            if origin_step >= floor and origin_step not in schedule and origin_step in existing_set:
                schedule.add(origin_step)
                pending.add(origin_step)

    def _schedule_list(self, steps_file: Path) -> Tuple[List[int], Set[int]]:
        existing_set: Set[int] = set(self.existing_step_indexes())
        lines: List[str] = steps_file.read_text(encoding="utf-8").splitlines()
        ordered_indexes: List[int] = [int(line.strip()) for line in lines if line.strip()]
        self._require_all_existing(ordered_indexes, existing_set)
        return ordered_indexes, set(ordered_indexes)

    @staticmethod
    def _require_all_existing(indexes: Iterable[int], existing_set: Set[int]) -> None:
        missing: List[int] = sorted({index for index in indexes if index not in existing_set})
        if missing:
            raise ValueError(
                f"ReplayRunner: step(s) {missing} não existem no workspace (nenhum curl file em disco) — "
                f"provavelmente foram pulados por skip_rules ou estão fora do intervalo de steps existentes."
            )

    def existing_step_indexes(self) -> List[int]:
        indexes: List[int] = []
        for path in self.workspace.curls.glob("req_*.curl.sh"):
            match: Optional[Match[str]] = self.STEP_FILENAME_PATTERN.match(path.name)
            if match is not None:
                indexes.append(int(match.group(1)))
        return sorted(indexes)
