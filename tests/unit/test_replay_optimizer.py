from pathlib import Path
from typing import List, Optional, Set, Tuple

import pytest

from har_reproducer.fs_io.workspace import Workspace
from har_reproducer.models import StatusCodeCriterion, StepResponse, SuccessCriterion
from har_reproducer.optimization.replay_optimizer import ReplayOptimizer, ReplayOptimizerAborted
from tests.support.fake_schedule_executor import FakeScheduleExecutor, RecordedExecuteScheduleCall

SUCCESS_CRITERIA: List[SuccessCriterion] = [StatusCodeCriterion(type="status_code", expected=200)]


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


def _ok(status_code: int = 200) -> StepResponse:
    return StepResponse(status_code=status_code)


def test_run_phase2_range_resolved_by_shortcut_alone_yields_empty_kept() -> None:
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([6, 9], {6, 9}),
        existing_indexes=[6, 7, 8, 9],
        responses_by_call=[{9: _ok(200)}],
    )
    optimizer: ReplayOptimizer = _optimizer(executor)

    kept: List[int] = optimizer._run_phase2(6, 9, anchors=[6, 9], backbone=[6], success_criteria=SUCCESS_CRITERIA)

    assert kept == []
    assert len(executor.calls) == 1
    assert executor.calls[0].ordered_indexes == [9]


def test_range_without_candidates_only_calls_shortcut() -> None:
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([8, 9], {8, 9}),
        existing_indexes=[8, 9],
        responses_by_call=[{9: _ok(200)}],
    )
    optimizer: ReplayOptimizer = _optimizer(executor)

    kept: List[int] = optimizer._run_phase2(8, 9, anchors=[8, 9], backbone=[8], success_criteria=SUCCESS_CRITERIA)

    assert kept == []
    assert len(executor.calls) == 1


def test_range_without_candidates_shortcut_failure_aborts() -> None:
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([8, 9], {8, 9}),
        existing_indexes=[8, 9],
        responses_by_call=[{9: _ok(404)}],
    )
    optimizer: ReplayOptimizer = _optimizer(executor)

    with pytest.raises(ReplayOptimizerAborted):
        optimizer._run_phase2(8, 9, anchors=[8, 9], backbone=[8], success_criteria=SUCCESS_CRITERIA)

    assert len(executor.calls) == 1


def test_run_phase2_elimination_keeps_only_the_necessary_candidate_closest_to_left() -> None:
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([6, 9], {6, 9}),
        existing_indexes=[6, 7, 8, 9],
        responses_by_call=[
            {9: _ok(404)},
            {9: _ok(200)},
            {9: _ok(200)},
            {9: _ok(404)},
        ],
    )
    optimizer: ReplayOptimizer = _optimizer(executor)

    kept: List[int] = optimizer._run_phase2(6, 9, anchors=[6, 9], backbone=[6], success_criteria=SUCCESS_CRITERIA)

    assert kept == [7]
    assert len(executor.calls) == 4
    assert executor.calls[0].ordered_indexes == [9]
    assert executor.calls[1].ordered_indexes == [7, 8, 9]
    assert executor.calls[2].ordered_indexes == [7, 9]
    assert executor.calls[3].ordered_indexes == [9]
    for call in executor.calls:
        assert all(index > 6 for index in call.ordered_indexes)


def test_run_phase2_carries_kept_from_target_facing_ranges_into_earlier_ranges() -> None:
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([0, 3, 9], {0, 3, 9}),
        existing_indexes=[0, 3, 4, 9],
        responses_by_call=[
            {9: _ok(404)},
            {9: _ok(200)},
            {9: _ok(404)},
            {9: _ok(200)},
        ],
    )
    optimizer: ReplayOptimizer = _optimizer(executor)

    kept: List[int] = optimizer._run_phase2(0, 9, anchors=[0, 3, 9], backbone=[0], success_criteria=SUCCESS_CRITERIA)

    assert kept == [4]
    assert executor.calls[3].ordered_indexes == [3, 4, 9]


def test_execute_retries_once_after_recoverable_status_then_succeeds() -> None:
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([0], {0}),
        existing_indexes=[0],
        responses_by_call=[
            {5: _ok(401)},
            {},
            {5: _ok(200)},
        ],
        reference_status_codes={5: 200},
    )
    optimizer: ReplayOptimizer = _optimizer(executor)
    optimizer.backbone = [0]

    results: List[Tuple[int, StepResponse]] = optimizer._execute([5], {5})

    assert [response.status_code for _, response in results] == [200]
    assert len(executor.calls) == 3
    assert executor.calls[1].ordered_indexes == [0]
    assert optimizer.requests_made == 3


def test_execute_gives_up_after_two_refreshes_and_returns_last_result() -> None:
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([0], {0}),
        existing_indexes=[0],
        default_response=_ok(401),
        reference_status_codes={5: 200},
    )
    optimizer: ReplayOptimizer = _optimizer(executor)
    optimizer.backbone = [0]

    results: List[Tuple[int, StepResponse]] = optimizer._execute([5], {5})

    assert [response.status_code for _, response in results] == [401]
    assert len(executor.calls) == 5
    assert optimizer.requests_made == 5


def test_execute_treats_transport_failure_status_zero_as_recoverable() -> None:
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([0], {0}),
        existing_indexes=[0],
        responses_by_call=[
            {5: _ok(0)},
            {},
            {5: _ok(200)},
        ],
    )
    optimizer: ReplayOptimizer = _optimizer(executor)
    optimizer.backbone = [0]

    results: List[Tuple[int, StepResponse]] = optimizer._execute([5], {5})

    assert [response.status_code for _, response in results] == [200]
    assert len(executor.calls) == 3


def test_run_phase2_elimination_restores_candidate_after_refreshes_exhausted() -> None:
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([8, 9], {8, 9}),
        existing_indexes=[8, 9],
        default_response=_ok(401),
        reference_status_codes={9: 200},
    )
    optimizer: ReplayOptimizer = _optimizer(executor)
    optimizer.backbone = [8]

    with pytest.raises(ReplayOptimizerAborted):
        optimizer._run_phase2(8, 9, anchors=[8, 9], backbone=[8], success_criteria=SUCCESS_CRITERIA)

    assert len(executor.calls) == 5


def test_execute_does_not_refresh_when_status_matches_reference() -> None:
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([0], {0}),
        existing_indexes=[0],
        default_response=_ok(403),
        reference_status_codes={5: 403},
    )
    optimizer: ReplayOptimizer = _optimizer(executor)
    optimizer.backbone = [0]

    results: List[Tuple[int, StepResponse]] = optimizer._execute([5], {5})

    assert [response.status_code for _, response in results] == [403]
    assert len(executor.calls) == 1


def test_optimize_end_to_end_success_writes_steps_file(tmp_path: Path) -> None:
    workspace: Workspace = Workspace(tmp_path)
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([6, 9], {6, 9}),
        existing_indexes=[6, 7, 8, 9],
        default_response=_ok(200),
    )
    optimizer: ReplayOptimizer = _optimizer(executor)

    result: Optional[List[int]] = optimizer.optimize(workspace, "run-1", 6, 9, SUCCESS_CRITERIA)

    assert result == [6, 9]
    written: str = workspace.optimized_steps_file("run-1").read_text(encoding="utf-8")
    assert written.splitlines() == ["6", "9"]


def test_optimize_confirmation_failure_writes_no_file_and_returns_none(tmp_path: Path) -> None:
    workspace: Workspace = Workspace(tmp_path)
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([6, 9], {6, 9}),
        existing_indexes=[6, 7, 8, 9],
        responses_by_call=[
            {6: _ok(200)},
            {9: _ok(200)},
            {9: _ok(404)},
        ],
    )
    optimizer: ReplayOptimizer = _optimizer(executor)

    result: Optional[List[int]] = optimizer.optimize(workspace, "run-1", 6, 9, SUCCESS_CRITERIA)

    assert result is None
    assert not workspace.optimized_steps_file("run-1").exists()


def test_optimize_final_list_has_no_duplicate_when_to_index_equals_from_index(tmp_path: Path) -> None:
    workspace: Workspace = Workspace(tmp_path)
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([5], {5}),
        existing_indexes=[5],
        default_response=_ok(200),
    )
    optimizer: ReplayOptimizer = _optimizer(executor)

    result: Optional[List[int]] = optimizer.optimize(workspace, "run-1", 5, 5, SUCCESS_CRITERIA)

    assert result == [5]


def test_optimize_range_abort_writes_no_file_and_returns_none(tmp_path: Path) -> None:
    workspace: Workspace = Workspace(tmp_path)
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([8, 9], {8, 9}),
        existing_indexes=[8, 9],
        default_response=_ok(404),
    )
    optimizer: ReplayOptimizer = _optimizer(executor)

    result: Optional[List[int]] = optimizer.optimize(workspace, "run-1", 8, 9, SUCCESS_CRITERIA)

    assert result is None
    assert not workspace.optimized_steps_file("run-1").exists()


def test_optimize_warns_before_overwriting_existing_steps_out(
        tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    workspace: Workspace = Workspace(tmp_path)
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([6, 9], {6, 9}),
        existing_indexes=[6, 7, 8, 9],
        default_response=_ok(200),
    )
    optimizer: ReplayOptimizer = _optimizer(executor)
    custom_output: Path = tmp_path / "custom.txt"
    custom_output.write_text("stale content\n", encoding="utf-8")

    result: Optional[List[int]] = optimizer.optimize(
        workspace, "run-1", 6, 9, SUCCESS_CRITERIA, output_path=custom_output
    )

    assert result == [6, 9]
    assert f"[AVISO] {custom_output} já existe e será sobrescrito." in capsys.readouterr().out
    assert custom_output.read_text(encoding="utf-8").splitlines() == ["6", "9"]


def test_optimize_does_not_warn_when_steps_out_does_not_exist_yet(
        tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    workspace: Workspace = Workspace(tmp_path)
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([6, 9], {6, 9}),
        existing_indexes=[6, 7, 8, 9],
        default_response=_ok(200),
    )
    optimizer: ReplayOptimizer = _optimizer(executor)
    custom_output: Path = tmp_path / "custom.txt"

    optimizer.optimize(workspace, "run-1", 6, 9, SUCCESS_CRITERIA, output_path=custom_output)

    assert "[AVISO]" not in capsys.readouterr().out


def test_reduce_anchors_removes_interior_anchor_when_target_alone_still_passes() -> None:
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([0, 153, 233], {0, 153, 233}),
        existing_indexes=[0, 153, 233],
        default_response=_ok(200),
    )
    optimizer: ReplayOptimizer = _optimizer(executor)

    reduced: List[int] = optimizer._reduce_anchors([0, 153, 233], 0, 233, [], SUCCESS_CRITERIA)

    assert reduced == []
    assert len(executor.calls) == 1
    assert executor.calls[0].ordered_indexes == [0, 233]


def test_reduce_anchors_keeps_interior_anchor_when_target_alone_fails() -> None:
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([0, 153, 233], {0, 153, 233}),
        existing_indexes=[0, 153, 233],
        default_response=_ok(404),
    )
    optimizer: ReplayOptimizer = _optimizer(executor)

    reduced: List[int] = optimizer._reduce_anchors([0, 153, 233], 0, 233, [], SUCCESS_CRITERIA)

    assert reduced == [153]
    assert len(executor.calls) == 1


def test_reduce_anchors_with_no_interior_anchor_makes_no_extra_call() -> None:
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([0, 9], {0, 9}),
        existing_indexes=[0, 9],
        default_response=_ok(200),
    )
    optimizer: ReplayOptimizer = _optimizer(executor)

    reduced: List[int] = optimizer._reduce_anchors([0, 9], 0, 9, [], SUCCESS_CRITERIA)

    assert reduced == []
    assert len(executor.calls) == 0


def test_optimize_end_to_end_reduces_interior_anchor_not_needed_by_target(tmp_path: Path) -> None:
    workspace: Workspace = Workspace(tmp_path)
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([0, 153, 233], {0, 153, 233}),
        existing_indexes=[0, 153, 233],
        default_response=_ok(200),
    )
    optimizer: ReplayOptimizer = _optimizer(executor)

    result: Optional[List[int]] = optimizer.optimize(workspace, "run-1", 0, 233, SUCCESS_CRITERIA)

    assert result == [0, 233]


def test_execute_raw_serves_second_call_for_same_backbone_index_from_cache_without_hitting_network() -> None:
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([0], {0}),
        existing_indexes=[0],
        responses_by_call=[{0: _ok(200)}, {0: _ok(999)}],
    )
    optimizer: ReplayOptimizer = _optimizer(executor)
    optimizer.backbone = [0]

    first: List[Tuple[int, StepResponse]] = optimizer._execute_raw([0], {0})
    second: List[Tuple[int, StepResponse]] = optimizer._execute_raw([0], {0})

    assert first[0][1].status_code == 200
    assert second[0][1].status_code == 200
    assert len(executor.calls) == 1


def test_execute_raw_force_refresh_ignores_cache_and_overwrites_it() -> None:
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([0], {0}),
        existing_indexes=[0],
        responses_by_call=[{0: _ok(200)}, {0: _ok(999)}],
    )
    optimizer: ReplayOptimizer = _optimizer(executor)
    optimizer.backbone = [0]

    optimizer._execute_raw([0], {0})
    forced: List[Tuple[int, StepResponse]] = optimizer._execute_raw([0], {0}, force_refresh=True)
    cached_again: List[Tuple[int, StepResponse]] = optimizer._execute_raw([0], {0})

    assert forced[0][1].status_code == 999
    assert len(executor.calls) == 2
    assert cached_again[0][1].status_code == 999
    assert len(executor.calls) == 2


def test_execute_raw_requests_made_counts_only_network_calls_not_cache_hits() -> None:
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([0], {0}),
        existing_indexes=[0],
        default_response=_ok(200),
    )
    optimizer: ReplayOptimizer = _optimizer(executor)
    optimizer.backbone = [0]

    optimizer._execute_raw([0], {0})
    optimizer._execute_raw([0], {0})

    assert optimizer.requests_made == 1


def test_execute_raw_does_not_cache_response_that_needs_recovery() -> None:
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([0], {0}),
        existing_indexes=[0],
        responses_by_call=[{0: _ok(500)}, {0: _ok(200)}],
        reference_status_codes={0: 200},
    )
    optimizer: ReplayOptimizer = _optimizer(executor)
    optimizer.backbone = [0]

    first: List[Tuple[int, StepResponse]] = optimizer._execute_raw([0], {0})
    second: List[Tuple[int, StepResponse]] = optimizer._execute_raw([0], {0})

    assert first[0][1].status_code == 500
    assert second[0][1].status_code == 200
    assert len(executor.calls) == 2


def test_execute_raw_does_not_cache_transport_failure_status_zero() -> None:
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([0], {0}),
        existing_indexes=[0],
        responses_by_call=[{0: _ok(0)}, {0: _ok(200)}],
    )
    optimizer: ReplayOptimizer = _optimizer(executor)
    optimizer.backbone = [0]

    first: List[Tuple[int, StepResponse]] = optimizer._execute_raw([0], {0})
    second: List[Tuple[int, StepResponse]] = optimizer._execute_raw([0], {0})

    assert first[0][1].status_code == 0
    assert second[0][1].status_code == 200
    assert len(executor.calls) == 2


def test_execute_raw_caches_response_when_index_has_no_reference_status_code() -> None:
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([0], {0}),
        existing_indexes=[0],
        responses_by_call=[{0: _ok(500)}, {0: _ok(999)}],
    )
    optimizer: ReplayOptimizer = _optimizer(executor)
    optimizer.backbone = [0]

    first: List[Tuple[int, StepResponse]] = optimizer._execute_raw([0], {0})
    second: List[Tuple[int, StepResponse]] = optimizer._execute_raw([0], {0})

    assert first[0][1].status_code == 500
    assert second[0][1].status_code == 500
    assert len(executor.calls) == 1


def test_execute_raw_never_caches_indexes_outside_backbone() -> None:
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([0, 5], {0, 5}),
        existing_indexes=[0, 5],
        responses_by_call=[{5: _ok(200)}, {5: _ok(999)}],
    )
    optimizer: ReplayOptimizer = _optimizer(executor)
    optimizer.backbone = [0]

    first: List[Tuple[int, StepResponse]] = optimizer._execute_raw([5], {5})
    second: List[Tuple[int, StepResponse]] = optimizer._execute_raw([5], {5})

    assert first[0][1].status_code == 200
    assert second[0][1].status_code == 999
    assert len(executor.calls) == 2


def test_execute_raw_caches_multiple_backbone_indexes_independently() -> None:
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([0, 1], {0, 1}),
        existing_indexes=[0, 1],
        responses_by_call=[{0: _ok(200), 1: _ok(201)}],
    )
    optimizer: ReplayOptimizer = _optimizer(executor)
    optimizer.backbone = [0, 1]

    first: List[Tuple[int, StepResponse]] = optimizer._execute_raw([0, 1], {0, 1})
    second: List[Tuple[int, StepResponse]] = optimizer._execute_raw([0, 1], {0, 1})

    assert [r.status_code for _, r in first] == [200, 201]
    assert [r.status_code for _, r in second] == [200, 201]
    assert len(executor.calls) == 1


def test_execute_reactive_refresh_forces_real_reexecution_ignoring_cache() -> None:
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([0], {0}),
        existing_indexes=[0],
        responses_by_call=[
            {5: _ok(401)},
            {0: _ok(200)},
            {5: _ok(200)},
        ],
        reference_status_codes={5: 200},
    )
    optimizer: ReplayOptimizer = _optimizer(executor)
    optimizer.backbone = [0]
    optimizer._backbone_response_cache[0] = _ok(111)

    optimizer._execute([5], {5})

    assert executor.calls[1].ordered_indexes == [0]
    assert optimizer._backbone_response_cache[0].status_code == 200


def test_execute_reactive_refresh_final_diverging_response_is_never_cached() -> None:
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([0], {0}),
        existing_indexes=[0],
        default_response=_ok(401),
        reference_status_codes={0: 200, 5: 200},
    )
    optimizer: ReplayOptimizer = _optimizer(executor)
    optimizer.backbone = [0]

    results: List[Tuple[int, StepResponse]] = optimizer._execute([5], {5})

    assert [response.status_code for _, response in results] == [401]
    assert len(executor.calls) == 5
    assert 0 not in optimizer._backbone_response_cache


def test_optimize_end_to_end_executes_backbone_index_only_once_across_reduce_and_confirm(tmp_path: Path) -> None:
    workspace: Workspace = Workspace(tmp_path)
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([0, 153, 233], {0, 153, 233}),
        existing_indexes=[0, 153, 233],
        default_response=_ok(200),
    )
    optimizer: ReplayOptimizer = _optimizer(executor)

    result: Optional[List[int]] = optimizer.optimize(workspace, "run-1", 0, 233, SUCCESS_CRITERIA)

    assert result == [0, 233]
    assert sum(1 for call in executor.calls if 0 in call.ordered_indexes) == 1


def test_optimize_writes_to_custom_output_path_when_given(tmp_path: Path) -> None:
    workspace: Workspace = Workspace(tmp_path)
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([6, 9], {6, 9}),
        existing_indexes=[6, 7, 8, 9],
        default_response=_ok(200),
    )
    optimizer: ReplayOptimizer = _optimizer(executor)
    custom_output: Path = tmp_path / "custom.txt"

    result: Optional[List[int]] = optimizer.optimize(
        workspace, "run-1", 6, 9, SUCCESS_CRITERIA, output_path=custom_output
    )

    assert result == [6, 9]
    assert custom_output.read_text(encoding="utf-8").splitlines() == ["6", "9"]
    assert not workspace.optimized_steps_file("run-1").exists()
