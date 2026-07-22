from typing import Callable, Tuple, TypeAlias

from ..models import Step, StepRequest, StepResponse

StepExecutor: TypeAlias = Callable[[Step], Tuple[StepRequest, StepResponse]]
