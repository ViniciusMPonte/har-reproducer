from pathlib import Path

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
