from pathlib import Path

from har_reproducer.fs_io.workspace import Workspace


def test_init_materializes_all_eight_subdirectories(tmp_path: Path) -> None:
    workspace: Workspace = Workspace(tmp_path)

    for directory in (
            workspace.curls,
            workspace.real_responses,
            workspace.original_responses,
            workspace.real_requests,
            workspace.extractors,
            workspace.temp_extractors,
            workspace.mitm_capture,
            workspace.replays,
    ):
        assert directory.is_dir()


def test_two_instances_do_not_share_state(tmp_path: Path) -> None:
    workspace_a: Workspace = Workspace(tmp_path / "a")
    workspace_b: Workspace = Workspace(tmp_path / "b")

    workspace_a.response_file(0).write_text("x", encoding="utf-8")

    assert not workspace_b.response_file(0).exists()


def test_response_file_pads_index_to_four_digits(tmp_path: Path) -> None:
    workspace: Workspace = Workspace(tmp_path)

    assert workspace.response_file(7) == workspace.real_responses / "res_0007.json"


def test_curl_file_pads_index_to_four_digits(tmp_path: Path) -> None:
    workspace: Workspace = Workspace(tmp_path)

    assert workspace.curl_file(3) == workspace.curls / "req_0003.curl.sh"


def test_replay_run_dir_creates_directory(tmp_path: Path) -> None:
    workspace: Workspace = Workspace(tmp_path)

    replay_dir: Path = workspace.replay_run_dir("run-1")

    assert replay_dir.is_dir()


def test_get_mitmproxy_ca_path_does_not_create_directory() -> None:
    path: Path = Workspace.get_mitmproxy_ca_path()
    existed_before: bool = path.exists()

    Workspace.get_mitmproxy_ca_path()

    assert path.exists() == existed_before
