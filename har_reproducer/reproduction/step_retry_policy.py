from typing import Callable, ClassVar, Set

from har_reproducer.models import StepResponse


class StepRetryPolicy:
    MAX_STEP_ATTEMPTS: ClassVar[int] = 2
    RECOVERABLE_STATUS_CODES: ClassVar[Set[int]] = {400, 401}

    def execute(
            self,
            step_index: int,
            attempt_fn: Callable[[], StepResponse],
            recovery_fn: Callable[[StepResponse], bool],
    ) -> StepResponse:
        for attempt in range(self.MAX_STEP_ATTEMPTS):
            response: StepResponse = attempt_fn()
            is_last_attempt: bool = attempt == self.MAX_STEP_ATTEMPTS - 1
            if not is_last_attempt and recovery_fn(response):
                print(f"Recovery successful for step {step_index}. Retrying request...")
                continue
            return response
        raise RuntimeError(f"execute exhausted {self.MAX_STEP_ATTEMPTS} attempts for step {step_index}")
