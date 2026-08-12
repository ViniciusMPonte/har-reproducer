from pathlib import Path

from har_reproducer.fs_io.workspace import Workspace


def test_optimized_steps_file_lives_under_replays_named_by_run_id(tmp_path: Path) -> None:
    workspace: Workspace = Workspace(tmp_path)

    path: Path = workspace.optimized_steps_file("run-1")

    assert path == workspace.replays / "optimized_run-1.txt"


def test_optimized_steps_file_differs_per_run_id(tmp_path: Path) -> None:
    workspace: Workspace = Workspace(tmp_path)

    first: Path = workspace.optimized_steps_file("run-1")
    second: Path = workspace.optimized_steps_file("run-2")

    assert first != second


def test_curl_file_and_replay_run_dir_still_work_after_new_method(tmp_path: Path) -> None:
    workspace: Workspace = Workspace(tmp_path)

    assert workspace.curl_file(3) == workspace.curls / "req_0003.curl.sh"
    assert workspace.replay_run_dir("run-1") == workspace.replays / "run-1"
