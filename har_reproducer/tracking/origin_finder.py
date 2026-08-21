from typing import Any, ClassVar, Dict, List, Optional, Tuple

from har_reproducer.models import OriginContainer, OriginMatch
from har_reproducer.tracking.flow_vocabulary import FlowVocabulary
from har_reproducer.tracking.fragment_matcher import FragmentMatcher
from har_reproducer.tracking.response_corpus import ResponseCorpus
from har_reproducer.tracking.value_variants import ValueVariants


class OriginFinder:
    MIN_LENGTH: ClassVar[int] = 4

    def __init__(self, corpus: ResponseCorpus, flow_vocabulary: FlowVocabulary) -> None:
        self.corpus: ResponseCorpus = corpus
        self.flow_vocabulary: FlowVocabulary = flow_vocabulary

    def find(self, value: str, from_step_index: int, before_step_index: int) -> Optional[OriginMatch]:
        if len(value) < self.MIN_LENGTH:
            return None

        eligible: List[int] = [
            index for index in self.corpus.eligible_indexes(before_step_index)
            if index >= from_step_index
        ]
        if not eligible:
            return None

        for variant in ValueVariants.of(value):
            match: Optional[OriginMatch] = self._find_variant(eligible, variant, variant == value)
            if match is not None:
                return match
        return self._find_fragment(eligible, value)

    def _find_variant(self, eligible: List[int], variant: str, is_raw: bool) -> Optional[OriginMatch]:
        for step_index in eligible:
            text: Optional[str] = self.corpus.searchable_text(step_index)
            if text is None or variant not in text:
                continue
            if is_raw and self.flow_vocabulary.rejects(variant, step_index):
                continue
            return self._build_match(step_index, variant, is_raw)
        return None

    def _find_fragment(self, eligible: List[int], value: str) -> Optional[OriginMatch]:
        winner: Optional[Tuple[str, int, int]] = None
        for step_index in eligible:
            text: Optional[str] = self.corpus.searchable_text(step_index)
            if text is None:
                continue
            candidate: Optional[Tuple[str, int]] = FragmentMatcher.longest_common(value, text)
            if candidate is None:
                continue
            fragment, offset = candidate
            if winner is None or self._is_better_fragment(fragment, offset, winner):
                winner = (fragment, offset, step_index)

        if winner is None:
            return None

        fragment, _, step_index = winner
        if len(fragment) < self.MIN_LENGTH:
            return None
        if self.flow_vocabulary.rejects(fragment, step_index):
            return None
        return self._build_match(step_index, fragment, is_raw=True, fragment=fragment)

    @staticmethod
    def _is_better_fragment(fragment: str, offset: int, winner: Tuple[str, int, int]) -> bool:
        winning_fragment, winning_offset, _ = winner
        if len(fragment) != len(winning_fragment):
            return len(fragment) > len(winning_fragment)
        return offset < winning_offset

    def _build_match(
            self, step_index: int, variant: str, is_raw: bool, fragment: Optional[str] = None,
    ) -> OriginMatch:
        if not is_raw:
            return OriginMatch(step_index=step_index)

        origin: Optional[Tuple[str, OriginContainer]] = self._origin_key(step_index, variant)
        if origin is None:
            return OriginMatch(step_index=step_index, fragment=fragment)

        return OriginMatch(step_index=step_index, origin_key=origin[0], origin_container=origin[1], fragment=fragment)

    def _origin_key(self, step_index: int, variant: str) -> Optional[Tuple[str, OriginContainer]]:
        response: Optional[Dict[str, Any]] = self.corpus.response(step_index)
        if response is None:
            return None

        cookie_key: Optional[str] = self._exact_key(response.get("cookies"), variant)
        if cookie_key is not None:
            return cookie_key, OriginContainer.COOKIE

        header_key: Optional[str] = self._exact_key(response.get("headers"), variant)
        if header_key is not None:
            return header_key, OriginContainer.HEADER

        return None

    @staticmethod
    def _exact_key(container: Optional[Dict[str, str]], variant: str) -> Optional[str]:
        for name, value in (container or {}).items():
            if value == variant:
                return name
        return None
