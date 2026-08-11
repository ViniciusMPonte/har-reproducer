from typing import List, Set, Tuple

import pytest

from har_reproducer.models import StepResponse
from har_reproducer.optimization.replay_optimizer import ReplayOptimizer
from tests.support.fake_schedule_executor import FakeScheduleExecutor, RecordedExecuteScheduleCall


def _optimizer(executor: FakeScheduleExecutor, max_requests: int = 500) -> ReplayOptimizer:
    return ReplayOptimizer(schedule_executor=executor, metadata_store=None, max_requests=max_requests)


def test_compute_backbone_stops_at_second_to_last_anchor(tmp_path=None) -> None:
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([0, 3, 6, 9], {0, 3, 6, 9}), existing_indexes=list(range(10))
    )
    optimizer: ReplayOptimizer = _optimizer(executor)

    backbone: List[int] = optimizer._compute_backbone(0, [0, 3, 6, 9])

    assert backbone == [0, 1, 2, 3, 4, 5, 6]


def test_compute_backbone_degenerate_single_anchor_is_just_from_index() -> None:
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([9], {9}), existing_indexes=list(range(10))
    )
    optimizer: ReplayOptimizer = _optimizer(executor)

    backbone: List[int] = optimizer._compute_backbone(0, [9])

    assert backbone == [0]


def test_run_phase1_calls_execute_schedule_once_with_backbone_and_annotate_false() -> None:
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([0, 3, 6, 9], {0, 3, 6, 9}), existing_indexes=list(range(10))
    )
    optimizer: ReplayOptimizer = _optimizer(executor)

    optimizer._run_phase1(0, 9)

    assert len(executor.calls) == 1
    call: RecordedExecuteScheduleCall = executor.calls[0]
    assert call.ordered_indexes == [0, 1, 2, 3, 4, 5, 6]
    assert call.schedule == {0, 1, 2, 3, 4, 5, 6}
    assert call.annotate is False


def test_run_phase1_increments_requests_made_by_backbone_size() -> None:
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([0, 3, 6, 9], {0, 3, 6, 9}), existing_indexes=list(range(10))
    )
    optimizer: ReplayOptimizer = _optimizer(executor)

    optimizer._run_phase1(0, 9)

    assert optimizer.requests_made == 7


def test_estimate_printed_before_phase1_warns_about_reactive_refresh(capsys: pytest.CaptureFixture[str]) -> None:
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([0, 3, 6, 9], {0, 3, 6, 9}), existing_indexes=list(range(10))
    )
    optimizer: ReplayOptimizer = _optimizer(executor)

    optimizer._run_phase1(0, 9)

    assert "refresh" in capsys.readouterr().out.lower()


def test_exceeding_max_requests_raises_value_error_with_counts() -> None:
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([0, 3, 6, 9], {0, 3, 6, 9}), existing_indexes=list(range(10))
    )
    optimizer: ReplayOptimizer = _optimizer(executor, max_requests=3)

    with pytest.raises(ValueError, match="3"):
        optimizer._run_phase1(0, 9)
