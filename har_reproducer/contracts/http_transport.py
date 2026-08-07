from typing import Protocol

from har_reproducer.models import StepResponse


class HttpTransport(Protocol):
    def send_request(self, curl_literal: str, step_index: int) -> StepResponse: ...
