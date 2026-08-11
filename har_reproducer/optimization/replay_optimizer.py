from typing import ClassVar, List, Set, Tuple

from har_reproducer.contracts import ScheduleExecutor
from har_reproducer.models import StepResponse, SuccessCriterion
from har_reproducer.reproduction import SilentExtractorMetadataStore
from har_reproducer.reproduction.step_retry_policy import StepRetryPolicy
from har_reproducer.validation import Validator


class ReplayOptimizerAborted(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason: str = reason


class ReplayOptimizer:
    RECOVERABLE_STATUS_CODES: ClassVar[Set[int]] = StepRetryPolicy.RECOVERABLE_STATUS_CODES | {0}
    MAX_REACTIVE_REFRESHES: ClassVar[int] = 2

    def __init__(
            self,
            schedule_executor: ScheduleExecutor,
            metadata_store: SilentExtractorMetadataStore,
            max_requests: int = 500,
    ) -> None:
        self.schedule_executor: ScheduleExecutor = schedule_executor
        self.metadata_store: SilentExtractorMetadataStore = metadata_store
        self.max_requests: int = max_requests
        self.requests_made: int = 0
        self.backbone: List[int] = []

    def _run_phase1(self, from_index: int, to_index: int) -> Tuple[List[int], List[int]]:
        anchors: List[int] = self.schedule_executor.compute_smart_schedule(from_index, to_index)[0]
        self._print_estimate(from_index, anchors)
        self.backbone = self._compute_backbone(from_index, anchors)
        self._execute(self.backbone, set(self.backbone))
        return anchors, self.backbone

    def _compute_backbone(self, from_index: int, anchors: List[int]) -> List[int]:
        boundary: int = anchors[-2] if len(anchors) >= 2 else from_index
        return [i for i in self.schedule_executor.existing_step_indexes() if from_index <= i <= boundary]

    def _execute(self, ordered_indexes: List[int], schedule: Set[int]) -> List[Tuple[int, StepResponse]]:
        refreshes: int = 0
        results: List[Tuple[int, StepResponse]] = self._execute_raw(ordered_indexes, schedule)
        while self._needs_reactive_refresh(results) and refreshes < self.MAX_REACTIVE_REFRESHES:
            refreshes += 1
            print(
                f"ReplayOptimizer: detected recoverable status in schedule — refreshing backbone before "
                f"retrying (attempt {refreshes}/{self.MAX_REACTIVE_REFRESHES})..."
            )
            self._execute_raw(self.backbone, set(self.backbone))
            results = self._execute_raw(ordered_indexes, schedule)
        return results

    def _execute_raw(self, ordered_indexes: List[int], schedule: Set[int]) -> List[Tuple[int, StepResponse]]:
        results: List[Tuple[int, StepResponse]] = self.schedule_executor.execute_schedule(
            ordered_indexes, schedule, annotate=False
        )
        self.requests_made += len(ordered_indexes)
        if self.requests_made > self.max_requests:
            raise ValueError(
                f"ReplayOptimizer: teto de requisições atingido ({self.requests_made}/{self.max_requests}) — "
                f"abortando a busca."
            )
        return results

    @classmethod
    def _needs_reactive_refresh(cls, results: List[Tuple[int, StepResponse]]) -> bool:
        return any(response.status_code in cls.RECOVERABLE_STATUS_CODES for _, response in results)

    def _run_phase2(
            self,
            from_index: int,
            to_index: int,
            anchors: List[int],
            backbone: List[int],
            success_criteria: List[SuccessCriterion],
    ) -> List[int]:
        kept: List[int] = []
        for left, right in self._ranges_target_to_from(from_index, anchors):
            kept += self._resolve_range(left, right, to_index, backbone, kept, success_criteria)
        return kept

    def _resolve_range(
            self,
            left: int,
            right: int,
            to_index: int,
            backbone: List[int],
            kept_so_far: List[int],
            success_criteria: List[SuccessCriterion],
    ) -> List[int]:
        if self._attempt(left, right, [], backbone, kept_so_far, to_index, success_criteria):
            return []

        candidates: List[int] = self._candidates_between(left, right)
        if not candidates or not self._attempt(left, right, candidates, backbone, kept_so_far, to_index, success_criteria):
            raise ReplayOptimizerAborted(
                f"ReplayOptimizer: faixa ({left}, {right}) falhou mesmo com todos os candidatos incluídos."
            )

        working: List[int] = list(candidates)
        for candidate in reversed(candidates):
            trial: List[int] = [c for c in working if c != candidate]
            if self._attempt(left, right, trial, backbone, kept_so_far, to_index, success_criteria):
                working = trial
        return working

    def _attempt(
            self,
            left: int,
            right: int,
            extra_candidates: List[int],
            backbone: List[int],
            kept_so_far: List[int],
            to_index: int,
            success_criteria: List[SuccessCriterion],
    ) -> bool:
        ordered_indexes: List[int] = sorted(set([right, to_index, *kept_so_far, *extra_candidates]))
        schedule: Set[int] = set(backbone) | set(kept_so_far) | set(ordered_indexes)
        results: List[Tuple[int, StepResponse]] = self._execute(ordered_indexes, schedule)
        target_response: StepResponse = next(response for index, response in results if index == to_index)
        return Validator.validate(target_response, success_criteria)

    def _ranges_target_to_from(self, from_index: int, anchors: List[int]) -> List[Tuple[int, int]]:
        ranges: List[Tuple[int, int]] = [
            (anchors[i], anchors[i + 1]) for i in range(len(anchors) - 2, -1, -1)
        ]
        if from_index < anchors[0]:
            ranges.append((from_index, anchors[0]))
        return ranges

    def _candidates_between(self, left: int, right: int) -> List[int]:
        return [i for i in self.schedule_executor.existing_step_indexes() if left < i < right]

    def _estimate_worst_case_requests(self, from_index: int, anchors: List[int]) -> int:
        ranges: List[Tuple[int, int]] = self._ranges_target_to_from(from_index, anchors)
        kept_acumulado: int = 0
        total: int = 0
        for left, right in ranges:
            k: int = len(self._candidates_between(left, right))
            total += (k + 2) * (k + kept_acumulado + 2)
            kept_acumulado += k
        return len(self._compute_backbone(from_index, anchors)) + total

    def _print_estimate(self, from_index: int, anchors: List[int]) -> None:
        estimate: int = self._estimate_worst_case_requests(from_index, anchors)
        print(
            f"ReplayOptimizer: worst-case estimate ≈ {estimate} requests (does NOT include reactive session "
            f"refreshes — unpredictable and disproportionately expensive, since each refresh re-runs the entire "
            f"backbone; calibrate --max-requests with headroom above this estimate when the backbone is large)."
        )
