from pathlib import Path
from typing import List, Optional, Set, Tuple

import pytest

from har_reproducer.contracts import HttpTransport
from har_reproducer.fs_io.workspace import Workspace
from har_reproducer.models import StepResponse
from har_reproducer.replay.curl_token_comment import CurlTokenComment, OriginStatusPhrase, ReplayStatusPhrase
from har_reproducer.replay.replay_result_comparator import ReplayResultComparator
from har_reproducer.replay.replay_runner import ReplayRunner
from har_reproducer.replay.replay_token_resolver import ReplayTokenResolver
from har_reproducer.reproduction.step_retry_policy import StepRetryPolicy
from har_reproducer.session.session_store import SessionStore
from tests.support.stub_http_transport import StubHttpTransport

_CURL_TOKEN_COMMENT: CurlTokenComment = CurlTokenComment(step_index_width=4)


class FakeReplayTokenResolver:

    def __init__(self, static_token_ids: Set[str], fallback_token_ids: Optional[Set[str]] = None) -> None:
        self.static_token_ids: Set[str] = static_token_ids
        self.fallback_token_ids: Set[str] = fallback_token_ids or set()

    def resolve(
            self,
            curl_text: str,
            schedule: Set[int],
            replay_run_dir: Path,
            res_refer_dir: Path,
            original_responses_dir: Path,
    ) -> Tuple[Set[str], Set[str]]:
        return self.static_token_ids, self.fallback_token_ids


def _runner(
        workspace: Workspace,
        replay_token_resolver: Optional[ReplayTokenResolver] = None,
        http_transport: Optional[HttpTransport] = None,
) -> ReplayRunner:
    return ReplayRunner(
        workspace=workspace,
        curl_token_comment=_CURL_TOKEN_COMMENT,
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


def test_compute_smart_schedule_expands_through_dependency_chain(tmp_path: Path) -> None:
    workspace: Workspace = Workspace(tmp_path)
    workspace.curl_file(2).write_text("curl -X GET https://x", encoding="utf-8")
    workspace.curl_file(5).write_text(
        _CURL_TOKEN_COMMENT.format_dependency_line("abc", 2) + "\ncurl -X GET https://y", encoding="utf-8"
    )
    runner: ReplayRunner = _runner(workspace)

    ordered: List[int]
    schedule: Set[int]
    ordered, schedule = runner.compute_smart_schedule(None, 5)

    assert schedule == {2, 5}


def test_compute_smart_schedule_still_expands_after_dependency_annotated_as_static(tmp_path: Path) -> None:
    workspace: Workspace = Workspace(tmp_path)
    workspace.curl_file(2).write_text("curl -X GET https://x", encoding="utf-8")
    workspace.curl_file(5).write_text(
        _CURL_TOKEN_COMMENT.format_dependency_line("abc", 2) + "\ncurl -X GET https://y", encoding="utf-8"
    )
    runner: ReplayRunner = _runner(workspace, replay_token_resolver=FakeReplayTokenResolver({"abc"}))
    runner._run_step(5, schedule={5})

    ordered: List[int]
    schedule: Set[int]
    ordered, schedule = runner.compute_smart_schedule(None, 5)

    assert schedule == {2, 5}


def test_compute_smart_schedule_does_not_anchor_on_dependency_with_origin_status_undetermined(
        tmp_path: Path
) -> None:
    workspace: Workspace = Workspace(tmp_path)
    workspace.curl_file(2).write_text("curl -X GET https://x", encoding="utf-8")
    workspace.curl_file(5).write_text(
        _CURL_TOKEN_COMMENT.format_dependency_line("abc", 2, OriginStatusPhrase.UNDETERMINED)
        + "\ncurl -X GET https://y",
        encoding="utf-8",
    )
    runner: ReplayRunner = _runner(workspace)

    ordered: List[int]
    schedule: Set[int]
    ordered, schedule = runner.compute_smart_schedule(None, 5)

    assert schedule == {5}


def test_compute_smart_schedule_does_not_anchor_on_dependency_with_origin_status_extraction_exhausted(
        tmp_path: Path
) -> None:
    workspace: Workspace = Workspace(tmp_path)
    workspace.curl_file(2).write_text("curl -X GET https://x", encoding="utf-8")
    workspace.curl_file(5).write_text(
        _CURL_TOKEN_COMMENT.format_dependency_line("abc", 2, OriginStatusPhrase.EXTRACTION_EXHAUSTED)
        + "\ncurl -X GET https://y",
        encoding="utf-8",
    )
    runner: ReplayRunner = _runner(workspace)

    ordered: List[int]
    schedule: Set[int]
    ordered, schedule = runner.compute_smart_schedule(None, 5)

    assert schedule == {5}


def test_compute_smart_schedule_expands_transitively_but_stops_at_a_frozen_literal(tmp_path: Path) -> None:
    workspace: Workspace = Workspace(tmp_path)
    workspace.curl_file(2).write_text("curl -X GET https://x", encoding="utf-8")
    workspace.curl_file(5).write_text(
        _CURL_TOKEN_COMMENT.format_dependency_line("abc", 2, OriginStatusPhrase.UNDETERMINED)
        + "\ncurl -X GET https://y",
        encoding="utf-8",
    )
    workspace.curl_file(9).write_text(
        _CURL_TOKEN_COMMENT.format_dependency_line("def", 5) + "\ncurl -X GET https://z", encoding="utf-8"
    )
    runner: ReplayRunner = _runner(workspace)

    ordered: List[int]
    schedule: Set[int]
    ordered, schedule = runner.compute_smart_schedule(None, 9)

    assert schedule == {5, 9}


def test_existing_step_indexes_returns_sorted_indexes_from_workspace(tmp_path: Path) -> None:
    workspace: Workspace = Workspace(tmp_path)
    for index in (5, 0, 2):
        workspace.curl_file(index).write_text("curl -X GET https://x", encoding="utf-8")
    runner: ReplayRunner = _runner(workspace)

    assert runner.existing_step_indexes() == [0, 2, 5]


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


def test_apply_replay_status_appends_status_once(tmp_path: Path) -> None:
    runner: ReplayRunner = _runner(Workspace(tmp_path))
    text: str = _CURL_TOKEN_COMMENT.format_dependency_line("abc", 2) + "\ncurl -X GET https://x"

    once: str = runner._apply_replay_status(text, "abc", ReplayStatusPhrase.COULD_NOT_EXTRACT)
    twice: str = runner._apply_replay_status(once, "abc", ReplayStatusPhrase.COULD_NOT_EXTRACT)

    assert once.splitlines()[0].endswith(ReplayStatusPhrase.COULD_NOT_EXTRACT.value)
    assert twice == once


def test_apply_replay_status_leaves_text_unchanged_for_absent_token(tmp_path: Path) -> None:
    runner: ReplayRunner = _runner(Workspace(tmp_path))
    text: str = _CURL_TOKEN_COMMENT.format_dependency_line("abc", 2) + "\ncurl -X GET https://x"

    result: str = runner._apply_replay_status(text, "naoexiste", ReplayStatusPhrase.COULD_NOT_EXTRACT)

    assert result.splitlines() == text.splitlines()


def test_annotate_static_tokens_rewrites_file_only_when_text_changes(tmp_path: Path) -> None:
    workspace: Workspace = Workspace(tmp_path)
    workspace.curl_file(0).write_text(
        _CURL_TOKEN_COMMENT.format_dependency_line("abc", 2) + "\ncurl -X GET https://x", encoding="utf-8"
    )
    runner: ReplayRunner = _runner(workspace)
    before: float = workspace.curl_file(0).stat().st_mtime

    runner._annotate_static_tokens(0, set())
    unchanged: str = workspace.curl_file(0).read_text(encoding="utf-8")

    runner._annotate_static_tokens(0, {"abc"})
    changed: str = workspace.curl_file(0).read_text(encoding="utf-8")

    assert ReplayStatusPhrase.PROBABLY_STATIC.value not in unchanged
    assert ReplayStatusPhrase.PROBABLY_STATIC.value in changed


def test_run_schedule_hybrid_verdict_fails_when_intermediate_step_broken(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    workspace: Workspace = Workspace(tmp_path)
    for index in (1, 2):
        workspace.curl_file(index).write_text("curl -X GET https://x", encoding="utf-8")
        workspace.response_file(index).write_text('{"status_code": 200}', encoding="utf-8")
    runner: ReplayRunner = _runner(
        workspace, http_transport=StubHttpTransport([StepResponse(status_code=0), StepResponse(status_code=200)])
    )

    is_match: bool = runner._run_schedule([1, 2], {1, 2})

    assert is_match is False
    assert "steps diverged" in capsys.readouterr().out


def test_run_schedule_hybrid_verdict_succeeds_with_soft_intermediate_mismatch(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    workspace: Workspace = Workspace(tmp_path)
    for index in (1, 2):
        workspace.curl_file(index).write_text("curl -X GET https://x", encoding="utf-8")
        workspace.response_file(index).write_text('{"status_code": 200}', encoding="utf-8")
    runner: ReplayRunner = _runner(
        workspace, http_transport=StubHttpTransport([StepResponse(status_code=404), StepResponse(status_code=200)])
    )

    is_match: bool = runner._run_schedule([1, 2], {1, 2})

    assert is_match is True
    assert "Replay Validation Result: ✓ SUCCESS" in capsys.readouterr().out


def test_run_schedule_hybrid_verdict_all_ok(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    workspace: Workspace = Workspace(tmp_path)
    for index in (1, 2):
        workspace.curl_file(index).write_text("curl -X GET https://x", encoding="utf-8")
        workspace.response_file(index).write_text('{"status_code": 200}', encoding="utf-8")
    runner: ReplayRunner = _runner(
        workspace, http_transport=StubHttpTransport([StepResponse(status_code=200), StepResponse(status_code=200)])
    )

    is_match: bool = runner._run_schedule([1, 2], {1, 2})

    assert is_match is True
    assert "Replay Validation Result: ✓ SUCCESS" in capsys.readouterr().out


def test_print_step_report_prints_each_step_in_order(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    workspace: Workspace = Workspace(tmp_path)
    workspace.response_file(3).write_text('{"status_code": 200}', encoding="utf-8")
    workspace.response_file(4).write_text('{"status_code": 200}', encoding="utf-8")
    runner: ReplayRunner = _runner(workspace)

    runner._print_step_report(
        [(4, StepResponse(status_code=200), True), (3, StepResponse(status_code=200), True)]
    )

    stdout: str = capsys.readouterr().out
    assert "Step 4: ✓ matched (200 vs original 200)" in stdout
    assert "Step 3: ✓ matched (200 vs original 200)" in stdout
    assert stdout.index("Step 4") < stdout.index("Step 3")


def test_annotate_fallback_tokens_rewrites_file_only_when_text_changes(tmp_path: Path) -> None:
    workspace: Workspace = Workspace(tmp_path)
    workspace.curl_file(0).write_text(
        _CURL_TOKEN_COMMENT.format_dependency_line("abc", 2) + "\ncurl -X GET https://x", encoding="utf-8"
    )
    runner: ReplayRunner = _runner(workspace)

    runner._annotate_fallback_tokens(0, set())
    unchanged: str = workspace.curl_file(0).read_text(encoding="utf-8")

    runner._annotate_fallback_tokens(0, {"abc"})
    changed: str = workspace.curl_file(0).read_text(encoding="utf-8")

    assert ReplayStatusPhrase.COULD_NOT_EXTRACT.value not in unchanged
    assert ReplayStatusPhrase.COULD_NOT_EXTRACT.value in changed


def test_run_step_annotates_fallback_token_in_curl(tmp_path: Path) -> None:
    workspace: Workspace = Workspace(tmp_path)
    workspace.curl_file(0).write_text(
        _CURL_TOKEN_COMMENT.format_dependency_line("abc", 2) + "\ncurl -X GET https://x", encoding="utf-8"
    )
    runner: ReplayRunner = _runner(
        workspace, replay_token_resolver=FakeReplayTokenResolver(set(), fallback_token_ids={"abc"})
    )

    response: StepResponse = runner._run_step(0, schedule={0})

    assert response.status_code == 200
    annotated: str = workspace.curl_file(0).read_text(encoding="utf-8")
    assert ReplayStatusPhrase.COULD_NOT_EXTRACT.value in annotated


def test_run_step_persists_stub_transport_response(tmp_path: Path) -> None:
    workspace: Workspace = Workspace(tmp_path)
    workspace.curl_file(0).write_text("curl -X GET https://x", encoding="utf-8")
    transport: StubHttpTransport = StubHttpTransport(StepResponse(status_code=200))
    runner: ReplayRunner = _runner(workspace, http_transport=transport)

    response: StepResponse = runner._run_step(0, schedule={0})

    assert response.status_code == 200
    persisted: str = workspace.replay_response_file("run-1", 0).read_text(encoding="utf-8")
    assert '"status_code":200' in persisted.replace(" ", "")


def test_execute_schedule_raises_on_empty_schedule(tmp_path: Path) -> None:
    workspace: Workspace = Workspace(tmp_path)
    runner: ReplayRunner = _runner(workspace)

    with pytest.raises(ValueError, match="schedule vazio"):
        runner.execute_schedule([], set())


def test_execute_schedule_returns_index_response_pairs_without_comparator(tmp_path: Path) -> None:
    workspace: Workspace = Workspace(tmp_path)
    for index in (2, 5):
        workspace.curl_file(index).write_text("curl -X GET https://x", encoding="utf-8")
    runner: ReplayRunner = _runner(
        workspace, http_transport=StubHttpTransport([StepResponse(status_code=200), StepResponse(status_code=404)])
    )

    results: List[Tuple[int, StepResponse]] = runner.execute_schedule([2, 5], {2, 5})

    assert [index for index, _ in results] == [2, 5]
    assert [response.status_code for _, response in results] == [200, 404]


def test_execute_schedule_annotate_false_suppresses_curl_annotation(tmp_path: Path) -> None:
    workspace: Workspace = Workspace(tmp_path)
    workspace.curl_file(0).write_text(
        _CURL_TOKEN_COMMENT.format_dependency_line("abc", 2) + "\ncurl -X GET https://x", encoding="utf-8"
    )
    runner: ReplayRunner = _runner(
        workspace, replay_token_resolver=FakeReplayTokenResolver({"abc"})
    )

    runner.execute_schedule([0], {0}, annotate=False)

    assert ReplayStatusPhrase.PROBABLY_STATIC.value not in workspace.curl_file(0).read_text(encoding="utf-8")


def test_execute_schedule_annotate_true_default_keeps_curl_annotation(tmp_path: Path) -> None:
    workspace: Workspace = Workspace(tmp_path)
    workspace.curl_file(0).write_text(
        _CURL_TOKEN_COMMENT.format_dependency_line("abc", 2) + "\ncurl -X GET https://x", encoding="utf-8"
    )
    runner: ReplayRunner = _runner(
        workspace, replay_token_resolver=FakeReplayTokenResolver({"abc"})
    )

    runner.execute_schedule([0], {0})

    assert ReplayStatusPhrase.PROBABLY_STATIC.value in workspace.curl_file(0).read_text(encoding="utf-8")
