from typing import Dict, List, NamedTuple, Optional, Set, Tuple

from har_reproducer.models import StepResponse


class RecordedExecuteScheduleCall(NamedTuple):
    ordered_indexes: List[int]
    schedule: Set[int]
    annotate: bool


class FakeScheduleExecutor:

    def __init__(
            self,
            smart_schedule: Tuple[List[int], Set[int]],
            existing_indexes: List[int],
            responses_by_call: Optional[List[Dict[int, StepResponse]]] = None,
            default_response: StepResponse = StepResponse(status_code=200),
    ) -> None:
        self.smart_schedule: Tuple[List[int], Set[int]] = smart_schedule
        self.existing_indexes: List[int] = existing_indexes
        self.responses_by_call: List[Dict[int, StepResponse]] = responses_by_call or []
        self.default_response: StepResponse = default_response
        self.calls: List[RecordedExecuteScheduleCall] = []

    def execute_schedule(
            self, ordered_indexes: List[int], schedule: Set[int], annotate: bool = True
    ) -> List[Tuple[int, StepResponse]]:
        call_index: int = len(self.calls)
        self.calls.append(RecordedExecuteScheduleCall(list(ordered_indexes), set(schedule), annotate))
        overrides: Dict[int, StepResponse] = (
            self.responses_by_call[call_index] if call_index < len(self.responses_by_call) else {}
        )
        return [(index, overrides.get(index, self.default_response)) for index in ordered_indexes]

    def compute_smart_schedule(
            self, from_index: Optional[int], to_index: Optional[int]
    ) -> Tuple[List[int], Set[int]]:
        return self.smart_schedule

    def existing_step_indexes(self) -> List[int]:
        return self.existing_indexes
