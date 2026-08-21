from pathlib import Path
from typing import Optional

from har_reproducer.fs_io.workspace import Workspace
from har_reproducer.models import StepResponse
from har_reproducer.replay.replay_result_comparator import ReplayResultComparator


def test_matches_original_true_when_status_code_matches_real_response(tmp_path: Path) -> None:
    workspace: Workspace = Workspace(tmp_path)
    workspace.response_file(0).write_text('{"status_code": 200}', encoding="utf-8")
    comparator: ReplayResultComparator = ReplayResultComparator(workspace)

    assert comparator.matches_original(0, StepResponse(status_code=200)) is True


def test_matches_original_false_when_status_code_differs(tmp_path: Path) -> None:
    workspace: Workspace = Workspace(tmp_path)
    workspace.response_file(0).write_text('{"status_code": 200}', encoding="utf-8")
    comparator: ReplayResultComparator = ReplayResultComparator(workspace)

    assert comparator.matches_original(0, StepResponse(status_code=404)) is False


def test_matches_original_falls_back_to_original_responses(tmp_path: Path) -> None:
    workspace: Workspace = Workspace(tmp_path)
    workspace.original_response_file(1).write_text('{"status_code": 200}', encoding="utf-8")
    comparator: ReplayResultComparator = ReplayResultComparator(workspace)

    assert comparator.matches_original(1, StepResponse(status_code=200)) is True


def test_matches_original_false_when_no_reference_exists(tmp_path: Path) -> None:
    workspace: Workspace = Workspace(tmp_path)
    comparator: ReplayResultComparator = ReplayResultComparator(workspace)

    assert comparator.matches_original(2, StepResponse(status_code=200)) is False


def test_matches_original_false_when_reference_has_no_status_code(tmp_path: Path) -> None:
    workspace: Workspace = Workspace(tmp_path)
    workspace.response_file(0).write_text("{}", encoding="utf-8")
    comparator: ReplayResultComparator = ReplayResultComparator(workspace)

    assert comparator.matches_original(0, StepResponse(status_code=200)) is False


def test_original_status_code_returns_int_when_reference_has_status(tmp_path: Path) -> None:
    workspace: Workspace = Workspace(tmp_path)
    workspace.response_file(0).write_text('{"status_code": 200}', encoding="utf-8")
    comparator: ReplayResultComparator = ReplayResultComparator(workspace)

    result: Optional[int] = comparator.original_status_code(0)

    assert result == 200


def test_original_status_code_returns_none_without_reference(tmp_path: Path) -> None:
    workspace: Workspace = Workspace(tmp_path)
    comparator: ReplayResultComparator = ReplayResultComparator(workspace)

    result: Optional[int] = comparator.original_status_code(2)

    assert result is None


def test_original_status_code_returns_none_when_reference_has_no_status(tmp_path: Path) -> None:
    workspace: Workspace = Workspace(tmp_path)
    workspace.response_file(0).write_text("{}", encoding="utf-8")
    comparator: ReplayResultComparator = ReplayResultComparator(workspace)

    result: Optional[int] = comparator.original_status_code(0)

    assert result is None


def test_needs_recovery_true_for_transport_failure_without_any_reference(tmp_path: Path) -> None:
    workspace: Workspace = Workspace(tmp_path)
    comparator: ReplayResultComparator = ReplayResultComparator(workspace)

    assert comparator.needs_recovery(5, StepResponse(status_code=0)) is True


def test_needs_recovery_false_without_reference_and_healthy_status(tmp_path: Path) -> None:
    workspace: Workspace = Workspace(tmp_path)
    comparator: ReplayResultComparator = ReplayResultComparator(workspace)

    assert comparator.needs_recovery(5, StepResponse(status_code=200)) is False


def test_needs_recovery_true_when_status_diverges_from_reference(tmp_path: Path) -> None:
    workspace: Workspace = Workspace(tmp_path)
    workspace.original_response_file(5).write_text('{"status_code": 200}', encoding="utf-8")
    comparator: ReplayResultComparator = ReplayResultComparator(workspace)

    assert comparator.needs_recovery(5, StepResponse(status_code=401)) is True


def test_needs_recovery_false_when_status_matches_reference(tmp_path: Path) -> None:
    workspace: Workspace = Workspace(tmp_path)
    workspace.original_response_file(5).write_text('{"status_code": 200}', encoding="utf-8")
    comparator: ReplayResultComparator = ReplayResultComparator(workspace)

    assert comparator.needs_recovery(5, StepResponse(status_code=200)) is False


def test_needs_recovery_false_when_status_matches_legitimate_non_200_reference(tmp_path: Path) -> None:
    workspace: Workspace = Workspace(tmp_path)
    workspace.original_response_file(5).write_text('{"status_code": 403}', encoding="utf-8")
    comparator: ReplayResultComparator = ReplayResultComparator(workspace)

    assert comparator.needs_recovery(5, StepResponse(status_code=403)) is False
