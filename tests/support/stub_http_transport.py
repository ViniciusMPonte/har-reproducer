from typing import List, NamedTuple, Union

from har_reproducer.models import StepResponse


class RecordedHttpTransportCall(NamedTuple):
    curl_literal: str
    step_index: int


class StubHttpTransport:

    def __init__(self, responses: Union[StepResponse, List[StepResponse]]) -> None:
        self.responses: List[StepResponse] = responses if isinstance(responses, list) else [responses]
        self.calls: List[RecordedHttpTransportCall] = []

    def send_request(self, curl_literal: str, step_index: int) -> StepResponse:
        self.calls.append(RecordedHttpTransportCall(curl_literal, step_index))
        index: int = min(len(self.calls) - 1, len(self.responses) - 1)
        return self.responses[index]
