import re
from re import Match, Pattern
from typing import ClassVar, Optional

from har_reproducer.fs_io import Workspace
from har_reproducer.models import StepResponse


class ReplayResultComparator:
    STATUS_CODE_PATTERN: ClassVar[Pattern[str]] = re.compile(r'"status_code"\s*:\s*(\d+)')

    def matches_original(self, index: int, response: StepResponse) -> bool:
        original_text: Optional[str] = self._read_reference_text(index)
        if original_text is None:
            return False

        match: Optional[Match[str]] = self.STATUS_CODE_PATTERN.search(original_text)
        if match is None:
            print(f"Could not find status_code in original response for step {index} to compare.")
            return False
        return int(match.group(1)) == response.status_code

    @staticmethod
    def _read_reference_text(index: int) -> Optional[str]:
        for candidate in (Workspace.response_file(index), Workspace.original_response_file(index)):
            try:
                return candidate.read_text(encoding="utf-8")
            except Exception:
                continue
        print(
            f"Could not read reference response for step {index} to compare "
            f"(checked real_responses/ and original_responses/)."
        )
        return None
