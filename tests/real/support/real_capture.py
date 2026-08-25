from pathlib import Path
from typing import ClassVar

from har_reproducer.fs_io.workspace import Workspace
from har_reproducer.models import Step, StepRequest


class RealCapture:

    STEP_INDEX_WIDTH: ClassVar[int] = Workspace.STEP_INDEX_WIDTH

    def __init__(self, base_dir: Path) -> None:
        self.base_dir: Path = base_dir
        self.real_requests_dir: Path = base_dir / "real_requests"
        self.real_responses_dir: Path = base_dir / "real_responses"
        self.original_responses_dir: Path = base_dir / "original_responses"

    def step_request(self, index: int) -> StepRequest:
        path: Path = self.real_requests_dir / f"req_{index:0{self.STEP_INDEX_WIDTH}d}.json"
        return StepRequest.model_validate_json(path.read_text(encoding="utf-8"))

    def step(self, index: int) -> Step:
        return Step(index=index, request=self.step_request(index))
