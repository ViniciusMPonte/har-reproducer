from pathlib import Path
from typing import List, Optional, Set, Tuple

import pytest

from har_reproducer.contracts import HttpTransport
from har_reproducer.fs_io.workspace import Workspace
from har_reproducer.models import StepResponse
from har_reproducer.replay.curl_dependency_parser import CurlDependencyParser
from har_reproducer.replay.replay_result_comparator import ReplayResultComparator
from har_reproducer.replay.replay_runner import ReplayRunner
from har_reproducer.replay.replay_token_resolver import ReplayTokenResolver
from har_reproducer.reproduction.step_retry_policy import StepRetryPolicy
from har_reproducer.session.session_store import SessionStore
from tests.support.stub_http_transport import StubHttpTransport


class FakeReplayTokenResolver:

    def __init__(self, static_token_ids: Set[str]) -> None:
        self.static_token_ids: Set[str] = static_token_ids

    def resolve(
            self,
            curl_text: str,
            schedule: Set[int],
            replay_run_dir: Path,
            res_refer_dir: Path,
            original_responses_dir: Path,
    ) -> Tuple[Set[str], Set[str]]:
        return self.static_token_ids, set()


def _runner(
        workspace: Workspace,
        replay_token_resolver: Optional[ReplayTokenResolver] = None,
        http_transport: Optional[HttpTransport] = None,
) -> ReplayRunner:
    return ReplayRunner(
        workspace=workspace,
        dependency_parser=CurlDependencyParser(),
        session_store=SessionStore(),
        http_transport=http_transport or StubHttpTransport(StepResponse(status_code=200)),
        replay_token_resolver=replay_token_resolver or FakeReplayTokenResolver(set()),
        retry_policy=StepRetryPolicy(),
        comparator=ReplayResultComparator(workspace),
        run_id="run-1",
        replay_run_dir=workspace.replay_run_dir("run-1"),
        res_refer_dir=workspace.real_responses,
        original_responses_dir=workspace.original_responses,
    )


def test_schedule_all_returns_every_existing_step_ordered(tmp_path: Path) -> None:
    workspace: Workspace = Workspace(tmp_path)
    for index in (0, 2, 5):
        workspace.curl_file(index).write_text("curl -X GET https://x", encoding="utf-8")
    runner: ReplayRunner = _runner(workspace)

    ordered: List[int]
    schedule: Set[int]
    ordered, schedule = runner._schedule_all()

    assert ordered == [0, 2, 5]
    assert schedule == {0, 2, 5}


def test_schedule_slice_filters_by_closed_interval(tmp_path: Path) -> None:
    workspace: Workspace = Workspace(tmp_path)
    for index in (0, 2, 5):
        workspace.curl_file(index).write_text("curl -X GET https://x", encoding="utf-8")
    runner: ReplayRunner = _runner(workspace)

    ordered: List[int]
    schedule: Set[int]
    ordered, schedule = runner._schedule_slice(1, 4)

    assert ordered == [2]
    assert schedule == {2}


def test_schedule_smart_expands_through_dependency_chain(tmp_path: Path) -> None:
    workspace: Workspace = Workspace(tmp_path)
    workspace.curl_file(2).write_text("curl -X GET https://x", encoding="utf-8")
    workspace.curl_file(5).write_text(
        "# Token abc comes from response of step 2\ncurl -X GET https://y", encoding="utf-8"
    )
    runner: ReplayRunner = _runner(workspace)

    ordered: List[int]
    schedule: Set[int]
    ordered, schedule = runner._schedule_smart(None, 5)

    assert schedule == {2, 5}


def test_schedule_list_raises_when_step_does_not_exist(tmp_path: Path) -> None:
    workspace: Workspace = Workspace(tmp_path)
    workspace.curl_file(0).write_text("curl -X GET https://x", encoding="utf-8")
    steps_file: Path = tmp_path / "steps.txt"
    steps_file.write_text("0\n7\n", encoding="utf-8")
    runner: ReplayRunner = _runner(workspace)

    with pytest.raises(ValueError):
        runner._schedule_list(steps_file)


def test_run_schedule_raises_on_empty_schedule(tmp_path: Path) -> None:
    workspace: Workspace = Workspace(tmp_path)
    runner: ReplayRunner = _runner(workspace)

    with pytest.raises(ValueError, match="schedule vazio"):
        runner._run_schedule([], set())


def test_mark_token_static_appends_suffix_once() -> None:
    text: str = "# Token abc comes from response of step 2\ncurl -X GET https://x"

    once: str = ReplayRunner._mark_token_static(text, "abc")
    twice: str = ReplayRunner._mark_token_static(once, "abc")

    assert once.splitlines()[0].endswith(ReplayRunner.STATIC_WARNING_SUFFIX)
    assert twice == once


def test_mark_token_static_leaves_text_unchanged_for_absent_token() -> None:
    text: str = "# Token abc comes from response of step 2\ncurl -X GET https://x"

    result: str = ReplayRunner._mark_token_static(text, "naoexiste")

    assert result.splitlines() == text.splitlines()


def test_annotate_static_tokens_rewrites_file_only_when_text_changes(tmp_path: Path) -> None:
    workspace: Workspace = Workspace(tmp_path)
    workspace.curl_file(0).write_text(
        "# Token abc comes from response of step 2\ncurl -X GET https://x", encoding="utf-8"
    )
    runner: ReplayRunner = _runner(workspace)
    before: float = workspace.curl_file(0).stat().st_mtime

    runner._annotate_static_tokens(0, set())
    unchanged: str = workspace.curl_file(0).read_text(encoding="utf-8")

    runner._annotate_static_tokens(0, {"abc"})
    changed: str = workspace.curl_file(0).read_text(encoding="utf-8")

    assert "probably static" not in unchanged
    assert "probably static" in changed


def test_run_step_persists_stub_transport_response(tmp_path: Path) -> None:
    workspace: Workspace = Workspace(tmp_path)
    workspace.curl_file(0).write_text("curl -X GET https://x", encoding="utf-8")
    transport: StubHttpTransport = StubHttpTransport(StepResponse(status_code=200))
    runner: ReplayRunner = _runner(workspace, http_transport=transport)

    response: StepResponse = runner._run_step(0, schedule={0})

    assert response.status_code == 200
    persisted: str = workspace.replay_response_file("run-1", 0).read_text(encoding="utf-8")
    assert '"status_code":200' in persisted.replace(" ", "")
