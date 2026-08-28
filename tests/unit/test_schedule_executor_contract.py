from pathlib import Path
from typing import List, Set, Tuple

from har_reproducer.contracts import ScheduleExecutor
from har_reproducer.fs_io.workspace import Workspace
from har_reproducer.models import StepResponse
from har_reproducer.replay.curl_token_comment import CurlTokenComment
from har_reproducer.replay.replay_result_comparator import ReplayResultComparator
from har_reproducer.replay.replay_runner import ReplayRunner
from har_reproducer.reproduction.cookie_jar_curl_override import CookieJarCurlOverride
from har_reproducer.reproduction.step_retry_policy import StepRetryPolicy
from har_reproducer.session.cookie_jar import CookieJar
from har_reproducer.session.session_store import SessionStore
from tests.support.fake_schedule_executor import FakeScheduleExecutor
from tests.support.stub_http_transport import StubHttpTransport
from tests.unit.test_replay_runner import FakeReplayTokenResolver, _write_request_file


def test_replay_runner_satisfies_schedule_executor_protocol(tmp_path: Path) -> None:
    workspace: Workspace = Workspace(tmp_path)
    workspace.curl_file(0).write_text("curl -X GET https://x", encoding="utf-8")
    _write_request_file(workspace, 0)
    jar: CookieJar = CookieJar()
    runner: ReplayRunner = ReplayRunner(
        workspace=workspace,
        curl_token_comment=CurlTokenComment(step_index_width=4),
        session_store=SessionStore(),
        http_transport=StubHttpTransport(StepResponse(status_code=200)),
        replay_token_resolver=FakeReplayTokenResolver(set()),
        retry_policy=StepRetryPolicy(),
        comparator=ReplayResultComparator(workspace),
        run_id="run-1",
        replay_run_dir=workspace.replay_run_dir("run-1"),
        res_refer_dir=workspace.real_responses,
        original_responses_dir=workspace.original_responses,
        cookie_jar=jar,
        cookie_jar_curl_override=CookieJarCurlOverride(jar),
    )

    executor: ScheduleExecutor = runner

    assert executor.existing_step_indexes() == [0]
    results: List[Tuple[int, StepResponse]] = executor.execute_schedule([0], {0})
    assert results == [(0, StepResponse(status_code=200))]
    ordered: List[int]
    schedule: Set[int]
    ordered, schedule = executor.compute_smart_schedule(None, 0)
    assert (ordered, schedule) == ([0], {0})
    assert executor.needs_recovery(0, StepResponse(status_code=200)) is False


def test_fake_schedule_executor_satisfies_protocol() -> None:
    fake: FakeScheduleExecutor = FakeScheduleExecutor(smart_schedule=([1, 2], {1, 2}), existing_indexes=[1, 2])
    executor: ScheduleExecutor = fake

    assert executor.existing_step_indexes() == [1, 2]
    assert executor.compute_smart_schedule(None, 2) == ([1, 2], {1, 2})
    assert executor.execute_schedule([1], {1}) == [(1, StepResponse(status_code=200))]
    assert executor.needs_recovery(1, StepResponse(status_code=200)) is False


def test_fake_schedule_executor_needs_recovery_true_for_transport_failure() -> None:
    fake: FakeScheduleExecutor = FakeScheduleExecutor(smart_schedule=([1], {1}), existing_indexes=[1])

    assert fake.needs_recovery(1, StepResponse(status_code=0)) is True


def test_fake_schedule_executor_needs_recovery_false_without_configured_reference() -> None:
    fake: FakeScheduleExecutor = FakeScheduleExecutor(smart_schedule=([1], {1}), existing_indexes=[1])

    assert fake.needs_recovery(1, StepResponse(status_code=404)) is False


def test_fake_schedule_executor_needs_recovery_true_when_diverges_from_configured_reference() -> None:
    fake: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([1], {1}), existing_indexes=[1], reference_status_codes={1: 200}
    )

    assert fake.needs_recovery(1, StepResponse(status_code=401)) is True


def test_fake_schedule_executor_needs_recovery_false_when_matches_configured_reference() -> None:
    fake: FakeScheduleExecutor = FakeScheduleExecutor(
        smart_schedule=([1], {1}), existing_indexes=[1], reference_status_codes={1: 200}
    )

    assert fake.needs_recovery(1, StepResponse(status_code=200)) is False
