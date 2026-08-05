from typing import ClassVar

from har_reproducer.engines.engine import Engine
from har_reproducer.models import Step, StepResponse


class DryEngine(Engine):
    USES_NETWORK: ClassVar[bool] = False

    def execute_step(self, step: Step) -> StepResponse:
        assert step.response is not None
        return step.response

    def _persist_response_step(self, index: int, response: StepResponse) -> None:
        pass
