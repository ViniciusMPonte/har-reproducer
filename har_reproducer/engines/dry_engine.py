from typing import Tuple

from ..models import Step, StepRequest, StepResponse
from .engine import Engine


class DryEngine(Engine):

    def execute_step(self, step: Step) -> Tuple[StepRequest, StepResponse]:
        final_request: StepRequest = self.request_builder.build_final_request(step)
        self.request_builder.write_curl(step, final_request)
        assert step.response is not None
        return final_request, step.response
