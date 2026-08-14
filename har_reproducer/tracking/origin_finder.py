from typing import Any, Dict, List, Optional, Tuple

from har_reproducer.models import OriginContainer, OriginMatch
from har_reproducer.tracking.response_corpus import ResponseCorpus
from har_reproducer.tracking.value_variants import ValueVariants


class OriginFinder:

    def __init__(self, corpus: ResponseCorpus) -> None:
        self.corpus: ResponseCorpus = corpus

    def find(self, value: str, from_step_index: int, before_step_index: int) -> Optional[OriginMatch]:
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
        return None

    def _find_variant(self, eligible: List[int], variant: str, is_raw: bool) -> Optional[OriginMatch]:
        for step_index in eligible:
            text: Optional[str] = self.corpus.searchable_text(step_index)
            if text is None or variant not in text:
                continue
            return self._build_match(step_index, variant, is_raw)
        return None

    def _build_match(self, step_index: int, variant: str, is_raw: bool) -> OriginMatch:
        if not is_raw:
            return OriginMatch(step_index=step_index)

        origin: Optional[Tuple[str, OriginContainer]] = self._origin_key(step_index, variant)
        if origin is None:
            return OriginMatch(step_index=step_index)

        return OriginMatch(step_index=step_index, origin_key=origin[0], origin_container=origin[1])

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
