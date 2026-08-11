from typing import List, Optional, Set, Tuple

from har_reproducer.models import StepResponse


class FakeScheduleExecutor:

    def __init__(
            self,
            smart_schedule: Tuple[List[int], Set[int]],
            existing_indexes: List[int],
    ) -> None:
        self.smart_schedule: Tuple[List[int], Set[int]] = smart_schedule
        self.existing_indexes: List[int] = existing_indexes

    def execute_schedule(
            self, ordered_indexes: List[int], schedule: Set[int], annotate: bool = True
    ) -> List[Tuple[int, StepResponse]]:
        return [(index, StepResponse(status_code=200)) for index in ordered_indexes]

    def compute_smart_schedule(
            self, from_index: Optional[int], to_index: Optional[int]
    ) -> Tuple[List[int], Set[int]]:
        return self.smart_schedule

    def existing_step_indexes(self) -> List[int]:
        return self.existing_indexes
