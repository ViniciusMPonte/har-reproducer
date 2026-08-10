from typing import List

from har_reproducer.models import StepResponse
from har_reproducer.reproduction.step_retry_policy import StepRetryPolicy


def test_execute_returns_first_response_when_recovery_never_triggers() -> None:
    policy: StepRetryPolicy = StepRetryPolicy()
    calls: List[int] = []

    def attempt() -> StepResponse:
        calls.append(1)
        return StepResponse(status_code=200)

    response: StepResponse = policy.execute(0, attempt, lambda r: False)

    assert response.status_code == 200
    assert len(calls) == 1


def test_execute_retries_once_after_successful_recovery() -> None:
    policy: StepRetryPolicy = StepRetryPolicy()
    responses: List[StepResponse] = [StepResponse(status_code=401), StepResponse(status_code=200)]
    calls: List[int] = []

    def attempt() -> StepResponse:
        calls.append(1)
        return responses[len(calls) - 1]

    response: StepResponse = policy.execute(0, attempt, lambda r: r.status_code == 401)

    assert response.status_code == 200
    assert len(calls) == 2


def test_execute_never_exceeds_max_attempts_even_with_persistent_recovery() -> None:
    policy: StepRetryPolicy = StepRetryPolicy()
    calls: List[int] = []

    def attempt() -> StepResponse:
        calls.append(1)
        return StepResponse(status_code=401)

    response: StepResponse = policy.execute(0, attempt, lambda r: True)

    assert response.status_code == 401
    assert len(calls) == StepRetryPolicy.MAX_STEP_ATTEMPTS == 2
