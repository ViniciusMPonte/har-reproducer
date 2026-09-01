from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import pytest

from har_reproducer.fs_io.workspace import Workspace
from har_reproducer.models import StatusCodeCriterion, StepRequest, StepResponse, SuccessCriterion
from har_reproducer.optimization.replay_optimizer import ReplayOptimizer, ReplayOptimizerAborted
from har_reproducer.session.cookie_jar import CookieJar
from tests.support.fake_schedule_executor import FakeScheduleExecutor, RecordedExecuteScheduleCall

SUCCESS_CRITERIA: List[SuccessCriterion] = [StatusCodeCriterion(type="status_code", expected=200)]


class _JarSnapshotScheduleExecutor(FakeScheduleExecutor):

    def __init__(self, cookie_jar: CookieJar, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.cookie_jar: CookieJar = cookie_jar
        self.jar_snapshots: List[Dict[str, str]] = []

    def execute_schedule(
            self, ordered_indexes: List[int], schedule: Set[int], annotate: bool = True
    ) -> List[Tuple[int, StepResponse]]:
        self.jar_snapshots.append(self.cookie_jar.current("exemplo.com", 443, "/"))
        return super().execute_schedule(ordered_indexes, schedule, annotate)


def _optimizer(
        tmp_path: Path, executor: FakeScheduleExecutor, max_requests: int = 500,
        cookie_jar: Optional[CookieJar] = None,
) -> ReplayOptimizer:
    workspace: Workspace = Workspace(tmp_path)
    jar: CookieJar = cookie_jar if cookie_jar is not None else CookieJar()
    return ReplayOptimizer(
        schedule_executor=executor, metadata_store=None, max_requests=max_requests,
        workspace=workspace, cookie_jar=jar,
    )


def _write_request_file(tmp_path: Path, index: int, url: str = "https://exemplo.com/x") -> None:
    Workspace(tmp_path).request_file(index).write_text(
        StepRequest(url=url, method="GET").model_dump_json(), encoding="utf-8"
    )


def test_compute_backbone_stops_at_second_to_last_anchor(tmp_path: Path) -> None:
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([0, 3, 6, 9], {0, 3, 6, 9}), existing_indexes=list(range(10))
    )
    optimizer: ReplayOptimizer = _optimizer(tmp_path, executor)

    backbone: List[int] = optimizer._compute_backbone(0, [0, 3, 6, 9])

    assert backbone == [0, 1, 2, 3, 4, 5, 6]


def test_compute_backbone_degenerate_single_anchor_is_just_from_index(tmp_path: Path) -> None:
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([9], {9}), existing_indexes=list(range(10))
    )
    optimizer: ReplayOptimizer = _optimizer(tmp_path, executor)

    backbone: List[int] = optimizer._compute_backbone(0, [9])

    assert backbone == [0]


def test_run_phase1_calls_execute_schedule_once_with_backbone_and_annotate_false(tmp_path: Path) -> None:
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([0, 3, 6, 9], {0, 3, 6, 9}), existing_indexes=list(range(10))
    )
    optimizer: ReplayOptimizer = _optimizer(tmp_path, executor)

    optimizer._run_phase1(0, 9)

    assert len(executor.calls) == 1
    call: RecordedExecuteScheduleCall = executor.calls[0]
    assert call.ordered_indexes == [0, 1, 2, 3, 4, 5, 6]
    assert call.schedule == {0, 1, 2, 3, 4, 5, 6}
    assert call.annotate is False


def test_run_phase1_increments_requests_made_by_backbone_size(tmp_path: Path) -> None:
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([0, 3, 6, 9], {0, 3, 6, 9}), existing_indexes=list(range(10))
    )
    optimizer: ReplayOptimizer = _optimizer(tmp_path, executor)

    optimizer._run_phase1(0, 9)

    assert optimizer.requests_made == 7


def test_estimate_printed_before_phase1_warns_about_reactive_refresh(
        tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([0, 3, 6, 9], {0, 3, 6, 9}), existing_indexes=list(range(10))
    )
    optimizer: ReplayOptimizer = _optimizer(tmp_path, executor)

    optimizer._run_phase1(0, 9)

    assert "refresh" in capsys.readouterr().out.lower()


def test_exceeding_max_requests_raises_value_error_with_counts(tmp_path: Path) -> None:
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([0, 3, 6, 9], {0, 3, 6, 9}), existing_indexes=list(range(10))
    )
    optimizer: ReplayOptimizer = _optimizer(tmp_path, executor, max_requests=3)

    with pytest.raises(ValueError, match="3"):
        optimizer._run_phase1(0, 9)


def _ok(status_code: int = 200) -> StepResponse:
    return StepResponse(status_code=status_code)


def test_run_phase2_range_resolved_by_shortcut_alone_yields_empty_kept(tmp_path: Path) -> None:
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([6, 9], {6, 9}),
        existing_indexes=[6, 7, 8, 9],
        responses_by_call=[{9: _ok(200)}],
    )
    optimizer: ReplayOptimizer = _optimizer(tmp_path, executor)

    kept: List[int] = optimizer._run_phase2(6, 9, anchors=[6, 9], backbone=[6], success_criteria=SUCCESS_CRITERIA)

    assert kept == []
    assert len(executor.calls) == 1
    assert executor.calls[0].ordered_indexes == [9]


def test_range_without_candidates_only_calls_shortcut(tmp_path: Path) -> None:
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([8, 9], {8, 9}),
        existing_indexes=[8, 9],
        responses_by_call=[{9: _ok(200)}],
    )
    optimizer: ReplayOptimizer = _optimizer(tmp_path, executor)

    kept: List[int] = optimizer._run_phase2(8, 9, anchors=[8, 9], backbone=[8], success_criteria=SUCCESS_CRITERIA)

    assert kept == []
    assert len(executor.calls) == 1


def test_range_without_candidates_shortcut_failure_aborts(tmp_path: Path) -> None:
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([8, 9], {8, 9}),
        existing_indexes=[8, 9],
        responses_by_call=[{9: _ok(404)}],
    )
    optimizer: ReplayOptimizer = _optimizer(tmp_path, executor)

    with pytest.raises(ReplayOptimizerAborted):
        optimizer._run_phase2(8, 9, anchors=[8, 9], backbone=[8], success_criteria=SUCCESS_CRITERIA)

    assert len(executor.calls) == 1


def test_run_phase2_elimination_keeps_only_the_necessary_candidate_closest_to_left(tmp_path: Path) -> None:
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
    optimizer: ReplayOptimizer = _optimizer(tmp_path, executor)

    kept: List[int] = optimizer._run_phase2(6, 9, anchors=[6, 9], backbone=[6], success_criteria=SUCCESS_CRITERIA)

    assert kept == [7]
    assert len(executor.calls) == 4
    assert executor.calls[0].ordered_indexes == [9]
    assert executor.calls[1].ordered_indexes == [7, 8, 9]
    assert executor.calls[2].ordered_indexes == [7, 9]
    assert executor.calls[3].ordered_indexes == [9]
    for call in executor.calls:
        assert all(index > 6 for index in call.ordered_indexes)


def test_resolve_range_with_empty_required_matches_existing_non_regression_scenario(tmp_path: Path) -> None:
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
    optimizer: ReplayOptimizer = _optimizer(tmp_path, executor)

    resolved: List[int] = optimizer._resolve_range(
        6, 9, 9, backbone=[6], kept_so_far=[], success_criteria=SUCCESS_CRITERIA, required=set(),
    )

    assert resolved == [7]
    assert len(executor.calls) == 4
    assert executor.calls[0].ordered_indexes == [9]
    assert executor.calls[1].ordered_indexes == [7, 8, 9]
    assert executor.calls[2].ordered_indexes == [7, 9]
    assert executor.calls[3].ordered_indexes == [9]


def test_resolve_range_keeps_required_candidate_that_search_would_otherwise_remove(tmp_path: Path) -> None:
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([6, 9], {6, 9}),
        existing_indexes=[6, 7, 9],
        default_response=_ok(200),
    )
    optimizer: ReplayOptimizer = _optimizer(tmp_path, executor)

    without_required: List[int] = optimizer._resolve_range(
        6, 9, 9, backbone=[6], kept_so_far=[], success_criteria=SUCCESS_CRITERIA, required=set(),
    )
    assert without_required == [], "pré-condição do teste: sem required, a busca remove o candidato 7"

    resolved: List[int] = optimizer._resolve_range(
        6, 9, 9, backbone=[6], kept_so_far=[], success_criteria=SUCCESS_CRITERIA, required={7},
    )

    assert resolved == [7]


def test_resolve_range_with_all_candidates_required_returns_them_all_without_aborting(tmp_path: Path) -> None:
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([6, 9], {6, 9}),
        existing_indexes=[6, 7, 8, 9],
        default_response=_ok(200),
    )
    optimizer: ReplayOptimizer = _optimizer(tmp_path, executor)

    resolved: List[int] = optimizer._resolve_range(
        6, 9, 9, backbone=[6], kept_so_far=[], success_criteria=SUCCESS_CRITERIA, required={7, 8},
    )

    assert set(resolved) == {7, 8}
    assert len(executor.calls) == 1
    assert executor.calls[0].ordered_indexes == [7, 8, 9]


def test_resolve_range_keeps_redundant_required_candidate_without_hiding_the_genuinely_necessary_one(
        tmp_path: Path,
) -> None:
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([6, 9], {6, 9}),
        existing_indexes=[6, 7, 8, 9],
        responses_by_call=[
            {9: _ok(404)},
            {9: _ok(200)},
            {9: _ok(404)},
        ],
    )
    optimizer: ReplayOptimizer = _optimizer(tmp_path, executor)

    resolved: List[int] = optimizer._resolve_range(
        6, 9, 9, backbone=[6], kept_so_far=[], success_criteria=SUCCESS_CRITERIA, required={8},
    )

    assert set(resolved) == {7, 8}
    assert executor.calls[0].ordered_indexes == [8, 9]
    assert executor.calls[1].ordered_indexes == [7, 8, 9]
    assert executor.calls[2].ordered_indexes == [8, 9]


def test_resolve_range_still_aborts_when_even_all_candidates_fail(tmp_path: Path) -> None:
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([6, 9], {6, 9}),
        existing_indexes=[6, 7, 8, 9],
        default_response=_ok(404),
    )
    optimizer: ReplayOptimizer = _optimizer(tmp_path, executor)

    with pytest.raises(ReplayOptimizerAborted):
        optimizer._resolve_range(
            6, 9, 9, backbone=[6], kept_so_far=[], success_criteria=SUCCESS_CRITERIA, required=set(),
        )


def test_run_phase2_carries_kept_from_target_facing_ranges_into_earlier_ranges(tmp_path: Path) -> None:
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
    optimizer: ReplayOptimizer = _optimizer(tmp_path, executor)

    kept: List[int] = optimizer._run_phase2(0, 9, anchors=[0, 3, 9], backbone=[0], success_criteria=SUCCESS_CRITERIA)

    assert kept == [4]
    assert executor.calls[3].ordered_indexes == [3, 4, 9]


def test_execute_retries_once_after_recoverable_status_then_succeeds(tmp_path: Path) -> None:
    _write_request_file(tmp_path, 0)
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
    optimizer: ReplayOptimizer = _optimizer(tmp_path, executor)
    optimizer.backbone = [0]

    results: List[Tuple[int, StepResponse]] = optimizer._execute([5], {5})

    assert [response.status_code for _, response in results] == [200]
    assert len(executor.calls) == 3
    assert executor.calls[1].ordered_indexes == [0]
    assert optimizer.requests_made == 3


def test_execute_gives_up_after_two_refreshes_and_returns_last_result(tmp_path: Path) -> None:
    _write_request_file(tmp_path, 0)
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([0], {0}),
        existing_indexes=[0],
        default_response=_ok(401),
        reference_status_codes={5: 200},
    )
    optimizer: ReplayOptimizer = _optimizer(tmp_path, executor)
    optimizer.backbone = [0]

    results: List[Tuple[int, StepResponse]] = optimizer._execute([5], {5})

    assert [response.status_code for _, response in results] == [401]
    assert len(executor.calls) == 5
    assert optimizer.requests_made == 5


def test_execute_treats_transport_failure_status_zero_as_recoverable(tmp_path: Path) -> None:
    _write_request_file(tmp_path, 0)
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([0], {0}),
        existing_indexes=[0],
        responses_by_call=[
            {5: _ok(0)},
            {},
            {5: _ok(200)},
        ],
    )
    optimizer: ReplayOptimizer = _optimizer(tmp_path, executor)
    optimizer.backbone = [0]

    results: List[Tuple[int, StepResponse]] = optimizer._execute([5], {5})

    assert [response.status_code for _, response in results] == [200]
    assert len(executor.calls) == 3


def test_run_phase2_elimination_restores_candidate_after_refreshes_exhausted(tmp_path: Path) -> None:
    _write_request_file(tmp_path, 8)
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([8, 9], {8, 9}),
        existing_indexes=[8, 9],
        default_response=_ok(401),
        reference_status_codes={9: 200},
    )
    optimizer: ReplayOptimizer = _optimizer(tmp_path, executor)
    optimizer.backbone = [8]

    with pytest.raises(ReplayOptimizerAborted):
        optimizer._run_phase2(8, 9, anchors=[8, 9], backbone=[8], success_criteria=SUCCESS_CRITERIA)

    assert len(executor.calls) == 5


def test_execute_does_not_refresh_when_status_matches_reference(tmp_path: Path) -> None:
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([0], {0}),
        existing_indexes=[0],
        default_response=_ok(403),
        reference_status_codes={5: 403},
    )
    optimizer: ReplayOptimizer = _optimizer(tmp_path, executor)
    optimizer.backbone = [0]

    results: List[Tuple[int, StepResponse]] = optimizer._execute([5], {5})

    assert [response.status_code for _, response in results] == [403]
    assert len(executor.calls) == 1


def test_optimize_end_to_end_success_writes_steps_file(tmp_path: Path) -> None:
    _write_request_file(tmp_path, 6)
    workspace: Workspace = Workspace(tmp_path)
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([6, 9], {6, 9}),
        existing_indexes=[6, 7, 8, 9],
        default_response=_ok(200),
    )
    optimizer: ReplayOptimizer = _optimizer(tmp_path, executor)

    result: Optional[List[int]] = optimizer.optimize(workspace, "run-1", 6, 9, SUCCESS_CRITERIA)

    assert result == [6, 9]
    written: str = workspace.optimized_steps_file("run-1").read_text(encoding="utf-8")
    assert written.splitlines() == ["6", "9"]


def test_optimize_confirmation_failure_writes_no_file_and_returns_none(tmp_path: Path) -> None:
    _write_request_file(tmp_path, 6)
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
    optimizer: ReplayOptimizer = _optimizer(tmp_path, executor)

    result: Optional[List[int]] = optimizer.optimize(workspace, "run-1", 6, 9, SUCCESS_CRITERIA)

    assert result is None
    assert not workspace.optimized_steps_file("run-1").exists()


def test_optimize_final_list_has_no_duplicate_when_to_index_equals_from_index(tmp_path: Path) -> None:
    _write_request_file(tmp_path, 5)
    workspace: Workspace = Workspace(tmp_path)
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([5], {5}),
        existing_indexes=[5],
        default_response=_ok(200),
    )
    optimizer: ReplayOptimizer = _optimizer(tmp_path, executor)

    result: Optional[List[int]] = optimizer.optimize(workspace, "run-1", 5, 5, SUCCESS_CRITERIA)

    assert result == [5]


def test_optimize_range_abort_writes_no_file_and_returns_none(tmp_path: Path) -> None:
    _write_request_file(tmp_path, 8)
    workspace: Workspace = Workspace(tmp_path)
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([8, 9], {8, 9}),
        existing_indexes=[8, 9],
        default_response=_ok(404),
    )
    optimizer: ReplayOptimizer = _optimizer(tmp_path, executor)

    result: Optional[List[int]] = optimizer.optimize(workspace, "run-1", 8, 9, SUCCESS_CRITERIA)

    assert result is None
    assert not workspace.optimized_steps_file("run-1").exists()


def test_optimize_warns_before_overwriting_existing_steps_out(
        tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    _write_request_file(tmp_path, 6)
    workspace: Workspace = Workspace(tmp_path)
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([6, 9], {6, 9}),
        existing_indexes=[6, 7, 8, 9],
        default_response=_ok(200),
    )
    optimizer: ReplayOptimizer = _optimizer(tmp_path, executor)
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
    _write_request_file(tmp_path, 6)
    workspace: Workspace = Workspace(tmp_path)
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([6, 9], {6, 9}),
        existing_indexes=[6, 7, 8, 9],
        default_response=_ok(200),
    )
    optimizer: ReplayOptimizer = _optimizer(tmp_path, executor)
    custom_output: Path = tmp_path / "custom.txt"

    optimizer.optimize(workspace, "run-1", 6, 9, SUCCESS_CRITERIA, output_path=custom_output)

    assert "[AVISO]" not in capsys.readouterr().out


def test_reduce_anchors_removes_interior_anchor_when_target_alone_still_passes(tmp_path: Path) -> None:
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([0, 153, 233], {0, 153, 233}),
        existing_indexes=[0, 153, 233],
        default_response=_ok(200),
    )
    optimizer: ReplayOptimizer = _optimizer(tmp_path, executor)

    reduced: List[int] = optimizer._reduce_anchors([0, 153, 233], 0, 233, [], SUCCESS_CRITERIA)

    assert reduced == []
    assert len(executor.calls) == 1
    assert executor.calls[0].ordered_indexes == [0, 233]


def test_reduce_anchors_keeps_interior_anchor_when_target_alone_fails(tmp_path: Path) -> None:
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([0, 153, 233], {0, 153, 233}),
        existing_indexes=[0, 153, 233],
        default_response=_ok(404),
    )
    optimizer: ReplayOptimizer = _optimizer(tmp_path, executor)

    reduced: List[int] = optimizer._reduce_anchors([0, 153, 233], 0, 233, [], SUCCESS_CRITERIA)

    assert reduced == [153]
    assert len(executor.calls) == 1


class _CookieGatedScheduleExecutor(FakeScheduleExecutor):
    """Simula um servidor real: o passo `gate_index` só responde 200 se o cookie
    `required_cookie` já estiver no jar no momento da chamada — exatamente o tipo de
    dependência que uma âncora de login estabelece (ex.: o step 92 no portal Unimed)."""

    def __init__(
            self, cookie_jar: CookieJar, gate_index: int, required_cookie: str,
            *args: object, **kwargs: object,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.cookie_jar: CookieJar = cookie_jar
        self.gate_index: int = gate_index
        self.required_cookie: str = required_cookie

    def execute_schedule(
            self, ordered_indexes: List[int], schedule: Set[int], annotate: bool = True,
    ) -> List[Tuple[int, StepResponse]]:
        self.calls.append(RecordedExecuteScheduleCall(list(ordered_indexes), set(schedule), annotate))
        results: List[Tuple[int, StepResponse]] = []
        for index in ordered_indexes:
            if index == self.gate_index:
                has_cookie: bool = self.required_cookie in self.cookie_jar.current("exemplo.com", 443, "/")
                results.append((index, _ok(200 if has_cookie else 401)))
            else:
                results.append((index, self.default_response))
        return results


def test_reduce_anchors_does_not_remove_an_anchor_whose_cookie_the_target_genuinely_needs(
        tmp_path: Path,
) -> None:
    """Reproduz o achado da investigação no portal Unimed (docs/20260829-2): uma âncora
    intermediária (step 50, análogo ao login) é a única fonte de um cookie ('auth') sem
    o qual o alvo (step 100) genuinamente falha — mas `_reduce_anchors` a remove mesmo
    assim, porque `_execute`/`_feed_cookie_jar_from_backbone_cache` sempre alimenta o
    jar com TODO `optimizer.backbone`, ignorando qual schedule está sendo testado no
    momento. O `.txt` exportado por `optimize` (sem o step 50) não reproduz o sucesso se
    replayado depois, sozinho, num processo novo — o jar desse processo novo nunca
    aprenderia o cookie 'auth', já que o step 50 nunca rodaria.

    Hoje este teste FALHA (reduced == [], não [50]) — é o teste vermelho para o fix."""
    _write_request_file(tmp_path, 0, url="https://exemplo.com/login")
    _write_request_file(tmp_path, 50, url="https://exemplo.com/login")
    jar: CookieJar = CookieJar()
    executor: _CookieGatedScheduleExecutor = _CookieGatedScheduleExecutor(
        jar, gate_index=100, required_cookie="auth",
        smart_schedule=([0, 50, 100], {0, 50, 100}), existing_indexes=[0, 50, 100],
    )
    optimizer: ReplayOptimizer = _optimizer(tmp_path, executor, cookie_jar=jar)
    optimizer.backbone = [0, 50]
    optimizer._backbone_response_cache[50] = StepResponse(status_code=200, cookies={"auth": "granted"})

    reduced: List[int] = optimizer._reduce_anchors([0, 50, 100], 0, 100, [], SUCCESS_CRITERIA)

    assert reduced == [50], (
        f"a âncora 50 foi removida ({reduced!r}) mesmo sendo a única fonte do cookie "
        f"'auth' que o alvo exige — _feed_cookie_jar_from_backbone_cache vazou o cookie "
        f"do backbone para o teste de remoção, mascarando a dependência real."
    )


def test_reduce_anchors_with_no_interior_anchor_makes_no_extra_call(tmp_path: Path) -> None:
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([0, 9], {0, 9}),
        existing_indexes=[0, 9],
        default_response=_ok(200),
    )
    optimizer: ReplayOptimizer = _optimizer(tmp_path, executor)

    reduced: List[int] = optimizer._reduce_anchors([0, 9], 0, 9, [], SUCCESS_CRITERIA)

    assert reduced == []
    assert len(executor.calls) == 0


def test_optimize_end_to_end_reduces_interior_anchor_not_needed_by_target(tmp_path: Path) -> None:
    _write_request_file(tmp_path, 0)
    _write_request_file(tmp_path, 153)
    workspace: Workspace = Workspace(tmp_path)
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([0, 153, 233], {0, 153, 233}),
        existing_indexes=[0, 153, 233],
        default_response=_ok(200),
    )
    optimizer: ReplayOptimizer = _optimizer(tmp_path, executor)

    result: Optional[List[int]] = optimizer.optimize(workspace, "run-1", 0, 233, SUCCESS_CRITERIA)

    assert result == [0, 233]


def test_execute_raw_serves_second_call_for_same_backbone_index_from_cache_without_hitting_network(
        tmp_path: Path,
) -> None:
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([0], {0}),
        existing_indexes=[0],
        responses_by_call=[{0: _ok(200)}, {0: _ok(999)}],
    )
    optimizer: ReplayOptimizer = _optimizer(tmp_path, executor)
    optimizer.backbone = [0]

    first: List[Tuple[int, StepResponse]] = optimizer._execute_raw([0], {0})
    second: List[Tuple[int, StepResponse]] = optimizer._execute_raw([0], {0})

    assert first[0][1].status_code == 200
    assert second[0][1].status_code == 200
    assert len(executor.calls) == 1


def test_execute_raw_force_refresh_ignores_cache_and_overwrites_it(tmp_path: Path) -> None:
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([0], {0}),
        existing_indexes=[0],
        responses_by_call=[{0: _ok(200)}, {0: _ok(999)}],
    )
    optimizer: ReplayOptimizer = _optimizer(tmp_path, executor)
    optimizer.backbone = [0]

    optimizer._execute_raw([0], {0})
    forced: List[Tuple[int, StepResponse]] = optimizer._execute_raw([0], {0}, force_refresh=True)
    cached_again: List[Tuple[int, StepResponse]] = optimizer._execute_raw([0], {0})

    assert forced[0][1].status_code == 999
    assert len(executor.calls) == 2
    assert cached_again[0][1].status_code == 999
    assert len(executor.calls) == 2


def test_execute_raw_requests_made_counts_only_network_calls_not_cache_hits(tmp_path: Path) -> None:
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([0], {0}),
        existing_indexes=[0],
        default_response=_ok(200),
    )
    optimizer: ReplayOptimizer = _optimizer(tmp_path, executor)
    optimizer.backbone = [0]

    optimizer._execute_raw([0], {0})
    optimizer._execute_raw([0], {0})

    assert optimizer.requests_made == 1


def test_execute_raw_does_not_cache_response_that_needs_recovery(tmp_path: Path) -> None:
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([0], {0}),
        existing_indexes=[0],
        responses_by_call=[{0: _ok(500)}, {0: _ok(200)}],
        reference_status_codes={0: 200},
    )
    optimizer: ReplayOptimizer = _optimizer(tmp_path, executor)
    optimizer.backbone = [0]

    first: List[Tuple[int, StepResponse]] = optimizer._execute_raw([0], {0})
    second: List[Tuple[int, StepResponse]] = optimizer._execute_raw([0], {0})

    assert first[0][1].status_code == 500
    assert second[0][1].status_code == 200
    assert len(executor.calls) == 2


def test_execute_raw_does_not_cache_transport_failure_status_zero(tmp_path: Path) -> None:
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([0], {0}),
        existing_indexes=[0],
        responses_by_call=[{0: _ok(0)}, {0: _ok(200)}],
    )
    optimizer: ReplayOptimizer = _optimizer(tmp_path, executor)
    optimizer.backbone = [0]

    first: List[Tuple[int, StepResponse]] = optimizer._execute_raw([0], {0})
    second: List[Tuple[int, StepResponse]] = optimizer._execute_raw([0], {0})

    assert first[0][1].status_code == 0
    assert second[0][1].status_code == 200
    assert len(executor.calls) == 2


def test_execute_raw_caches_response_when_index_has_no_reference_status_code(tmp_path: Path) -> None:
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([0], {0}),
        existing_indexes=[0],
        responses_by_call=[{0: _ok(500)}, {0: _ok(999)}],
    )
    optimizer: ReplayOptimizer = _optimizer(tmp_path, executor)
    optimizer.backbone = [0]

    first: List[Tuple[int, StepResponse]] = optimizer._execute_raw([0], {0})
    second: List[Tuple[int, StepResponse]] = optimizer._execute_raw([0], {0})

    assert first[0][1].status_code == 500
    assert second[0][1].status_code == 500
    assert len(executor.calls) == 1


def test_execute_raw_never_caches_indexes_outside_backbone(tmp_path: Path) -> None:
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([0, 5], {0, 5}),
        existing_indexes=[0, 5],
        responses_by_call=[{5: _ok(200)}, {5: _ok(999)}],
    )
    optimizer: ReplayOptimizer = _optimizer(tmp_path, executor)
    optimizer.backbone = [0]

    first: List[Tuple[int, StepResponse]] = optimizer._execute_raw([5], {5})
    second: List[Tuple[int, StepResponse]] = optimizer._execute_raw([5], {5})

    assert first[0][1].status_code == 200
    assert second[0][1].status_code == 999
    assert len(executor.calls) == 2


def test_execute_raw_caches_multiple_backbone_indexes_independently(tmp_path: Path) -> None:
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([0, 1], {0, 1}),
        existing_indexes=[0, 1],
        responses_by_call=[{0: _ok(200), 1: _ok(201)}],
    )
    optimizer: ReplayOptimizer = _optimizer(tmp_path, executor)
    optimizer.backbone = [0, 1]

    first: List[Tuple[int, StepResponse]] = optimizer._execute_raw([0, 1], {0, 1})
    second: List[Tuple[int, StepResponse]] = optimizer._execute_raw([0, 1], {0, 1})

    assert [r.status_code for _, r in first] == [200, 201]
    assert [r.status_code for _, r in second] == [200, 201]
    assert len(executor.calls) == 1


def test_execute_reactive_refresh_forces_real_reexecution_ignoring_cache(tmp_path: Path) -> None:
    _write_request_file(tmp_path, 0)
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
    optimizer: ReplayOptimizer = _optimizer(tmp_path, executor)
    optimizer.backbone = [0]
    optimizer._backbone_response_cache[0] = _ok(111)

    optimizer._execute([5], {5})

    assert executor.calls[1].ordered_indexes == [0]
    assert optimizer._backbone_response_cache[0].status_code == 200


def test_execute_reactive_refresh_final_diverging_response_is_never_cached(tmp_path: Path) -> None:
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([0], {0}),
        existing_indexes=[0],
        default_response=_ok(401),
        reference_status_codes={0: 200, 5: 200},
    )
    optimizer: ReplayOptimizer = _optimizer(tmp_path, executor)
    optimizer.backbone = [0]

    results: List[Tuple[int, StepResponse]] = optimizer._execute([5], {5})

    assert [response.status_code for _, response in results] == [401]
    assert len(executor.calls) == 5
    assert 0 not in optimizer._backbone_response_cache


def test_optimize_end_to_end_executes_backbone_index_only_once_across_reduce_and_confirm(tmp_path: Path) -> None:
    _write_request_file(tmp_path, 0)
    _write_request_file(tmp_path, 153)
    workspace: Workspace = Workspace(tmp_path)
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([0, 153, 233], {0, 153, 233}),
        existing_indexes=[0, 153, 233],
        default_response=_ok(200),
    )
    optimizer: ReplayOptimizer = _optimizer(tmp_path, executor)

    result: Optional[List[int]] = optimizer.optimize(workspace, "run-1", 0, 233, SUCCESS_CRITERIA)

    assert result == [0, 233]
    assert sum(1 for call in executor.calls if 0 in call.ordered_indexes) == 1


def test_optimize_writes_to_custom_output_path_when_given(tmp_path: Path) -> None:
    _write_request_file(tmp_path, 6)
    workspace: Workspace = Workspace(tmp_path)
    executor: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([6, 9], {6, 9}),
        existing_indexes=[6, 7, 8, 9],
        default_response=_ok(200),
    )
    optimizer: ReplayOptimizer = _optimizer(tmp_path, executor)
    custom_output: Path = tmp_path / "custom.txt"

    result: Optional[List[int]] = optimizer.optimize(
        workspace, "run-1", 6, 9, SUCCESS_CRITERIA, output_path=custom_output
    )

    assert result == [6, 9]
    assert custom_output.read_text(encoding="utf-8").splitlines() == ["6", "9"]
    assert not workspace.optimized_steps_file("run-1").exists()


def test_feed_cookie_jar_from_backbone_cache_populates_jar_for_cached_backbone_indexes(tmp_path: Path) -> None:
    _write_request_file(tmp_path, 0, url="https://exemplo.com/login")
    executor: FakeScheduleExecutor = FakeScheduleExecutor(smart_schedule=([0], {0}), existing_indexes=[0])
    optimizer: ReplayOptimizer = _optimizer(tmp_path, executor)
    optimizer.backbone = [0]
    optimizer._backbone_response_cache[0] = StepResponse(status_code=200, cookies={"sess": "abc"})

    optimizer._feed_cookie_jar_from_backbone_cache()

    assert optimizer.cookie_jar.current("exemplo.com", 443, "/") == {"sess": "abc"}


def test_feed_cookie_jar_from_backbone_cache_skips_indexes_without_cached_response(tmp_path: Path) -> None:
    _write_request_file(tmp_path, 0, url="https://exemplo.com/login")
    executor: FakeScheduleExecutor = FakeScheduleExecutor(smart_schedule=([0], {0}), existing_indexes=[0])
    optimizer: ReplayOptimizer = _optimizer(tmp_path, executor)
    optimizer.backbone = [0]

    optimizer._feed_cookie_jar_from_backbone_cache()

    assert optimizer.cookie_jar.current("exemplo.com", 443, "/") == {}


def test_execute_feeds_jar_from_backbone_cache_before_calling_execute_raw(tmp_path: Path) -> None:
    _write_request_file(tmp_path, 0, url="https://exemplo.com/login")
    jar: CookieJar = CookieJar()
    executor: _JarSnapshotScheduleExecutor = _JarSnapshotScheduleExecutor(
        jar, smart_schedule=([0], {0}), existing_indexes=[0], default_response=_ok(200),
    )
    optimizer: ReplayOptimizer = _optimizer(tmp_path, executor, cookie_jar=jar)
    optimizer.backbone = [0]
    optimizer._backbone_response_cache[0] = StepResponse(status_code=200, cookies={"sess": "abc"})

    optimizer._execute([5], {5})

    assert executor.jar_snapshots[0] == {"sess": "abc"}


def test_execute_resets_jar_before_each_call_removing_stale_state_from_previous_attempt(tmp_path: Path) -> None:
    _write_request_file(tmp_path, 0, url="https://exemplo.com/login")
    jar: CookieJar = CookieJar()
    executor: _JarSnapshotScheduleExecutor = _JarSnapshotScheduleExecutor(
        jar, smart_schedule=([0], {0}), existing_indexes=[0], default_response=_ok(200),
    )
    optimizer: ReplayOptimizer = _optimizer(tmp_path, executor, cookie_jar=jar)
    optimizer.backbone = [0]
    jar.feed("exemplo.com", 443, {"stale": "leftover"}, {})

    optimizer._execute([5], {5})

    assert "stale" not in executor.jar_snapshots[0]


def test_execute_reactive_refresh_refeeds_jar_from_newly_refreshed_backbone_before_final_retry(
        tmp_path: Path,
) -> None:
    _write_request_file(tmp_path, 0, url="https://exemplo.com/login")
    jar: CookieJar = CookieJar()
    executor: _JarSnapshotScheduleExecutor = _JarSnapshotScheduleExecutor(
        jar,
        smart_schedule=([0], {0}),
        existing_indexes=[0],
        responses_by_call=[
            {5: _ok(401)},
            {0: StepResponse(status_code=200, cookies={"sess": "refreshed"})},
            {5: _ok(200)},
        ],
        reference_status_codes={5: 200},
    )
    optimizer: ReplayOptimizer = _optimizer(tmp_path, executor, cookie_jar=jar)
    optimizer.backbone = [0]
    optimizer._backbone_response_cache[0] = StepResponse(status_code=200, cookies={"sess": "stale"})

    optimizer._execute([5], {5})

    assert executor.jar_snapshots[0] == {"sess": "stale"}
    assert executor.jar_snapshots[2] == {"sess": "refreshed"}
