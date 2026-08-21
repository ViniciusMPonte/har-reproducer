from typing import List, NamedTuple, Optional

from har_reproducer.models import OriginMatch
from har_reproducer.tracking.flow_vocabulary import FlowVocabulary
from har_reproducer.tracking.origin_finder import OriginFinder
from har_reproducer.tracking.response_corpus import ResponseCorpus


class RecordedFindCall(NamedTuple):
    value: str
    from_step_index: int
    before_step_index: int


class RecordingOriginFinder(OriginFinder):

    def __init__(self, corpus: ResponseCorpus, flow_vocabulary: FlowVocabulary) -> None:
        super().__init__(corpus, flow_vocabulary)
        self.find_calls: List[RecordedFindCall] = []

    def find(self, value: str, from_step_index: int, before_step_index: int) -> Optional[OriginMatch]:
        self.find_calls.append(RecordedFindCall(value, from_step_index, before_step_index))
        return super().find(value, from_step_index, before_step_index)
