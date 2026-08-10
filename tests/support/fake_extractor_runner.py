from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Union

from har_reproducer.models import Extractor


class RecordedRunCall(NamedTuple):
    token_id: str
    response_override_dir: Optional[Path]


class FakeExtractorRunner:

    def __init__(
            self,
            run_existing_result: Optional[str] = None,
            run_existing_by_token: Optional[Dict[str, Optional[str]]] = None,
            run_result: Union[Optional[str], Exception] = None,
    ) -> None:
        self.run_existing_result: Optional[str] = run_existing_result
        self.run_existing_by_token: Dict[str, Optional[str]] = run_existing_by_token or {}
        self.run_result: Union[Optional[str], Exception] = run_result
        self.run_existing_calls: List[RecordedRunCall] = []
        self.run_calls: List[RecordedRunCall] = []

    def run_existing(self, token_id: str, response_override_dir: Optional[Path] = None) -> Optional[str]:
        self.run_existing_calls.append(RecordedRunCall(token_id, response_override_dir))
        if token_id in self.run_existing_by_token:
            return self.run_existing_by_token[token_id]
        return self.run_existing_result

    def run(self, extractor: Extractor, response_override_dir: Optional[Path] = None) -> Optional[str]:
        self.run_calls.append(RecordedRunCall(extractor.token_id, response_override_dir))
        if isinstance(self.run_result, Exception):
            raise self.run_result
        return self.run_result
