from pathlib import Path
from typing import List, Set, Tuple

from har_reproducer.contracts import ScheduleExecutor
from har_reproducer.fs_io.workspace import Workspace
from har_reproducer.models import StepResponse
from har_reproducer.replay.curl_dependency_parser import CurlDependencyParser
from har_reproducer.replay.replay_result_comparator import ReplayResultComparator
from har_reproducer.replay.replay_runner import ReplayRunner
from har_reproducer.reproduction.step_retry_policy import StepRetryPolicy
from har_reproducer.session.session_store import SessionStore
from tests.support.fake_schedule_executor import FakeScheduleExecutor
from tests.support.stub_http_transport import StubHttpTransport
from tests.unit.test_replay_runner import FakeReplayTokenResolver


def test_replay_runner_satisfies_schedule_executor_protocol(tmp_path: Path) -> None:
    workspace: Workspace = Workspace(tmp_path)
    workspace.curl_file(0).write_text("curl -X GET https://x", encoding="utf-8")
    runner: ReplayRunner = ReplayRunner(
        workspace=workspace,
        dependency_parser=CurlDependencyParser(),
        session_store=SessionStore(),
        http_transport=StubHttpTransport(StepResponse(status_code=200)),
        replay_token_resolver=FakeReplayTokenResolver(set()),
        retry_policy=StepRetryPolicy(),
        comparator=ReplayResultComparator(workspace),
        run_id="run-1",
        replay_run_dir=workspace.replay_run_dir("run-1"),
        res_refer_dir=workspace.real_responses,
        original_responses_dir=workspace.original_responses,
    )

    executor: ScheduleExecutor = runner

    assert executor.existing_step_indexes() == [0]
    results: List[Tuple[int, StepResponse]] = executor.execute_schedule([0], {0})
    assert results == [(0, StepResponse(status_code=200))]
    ordered: List[int]
    schedule: Set[int]
    ordered, schedule = executor.compute_smart_schedule(None, 0)
    assert (ordered, schedule) == ([0], {0})


def test_fake_schedule_executor_satisfies_protocol() -> None:
    fake: FakeScheduleExecutor = FakeScheduleExecutor(smart_schedule=([1, 2], {1, 2}), existing_indexes=[1, 2])
    executor: ScheduleExecutor = fake

    assert executor.existing_step_indexes() == [1, 2]
    assert executor.compute_smart_schedule(None, 2) == ([1, 2], {1, 2})
    assert executor.execute_schedule([1], {1}) == [(1, StepResponse(status_code=200))]
