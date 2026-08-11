from typing import List, Optional, Protocol, Set, Tuple

from har_reproducer.models import StepResponse


class ScheduleExecutor(Protocol):
    def execute_schedule(
            self, ordered_indexes: List[int], schedule: Set[int], annotate: bool = True
    ) -> List[Tuple[int, StepResponse]]: ...

    def compute_smart_schedule(
            self, from_index: Optional[int], to_index: Optional[int]
    ) -> Tuple[List[int], Set[int]]: ...

    def existing_step_indexes(self) -> List[int]: ...
