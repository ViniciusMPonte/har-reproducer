import math
from typing import ClassVar, Optional, Tuple


class FragmentMatcher:
    MIN_COVERAGE: ClassVar[float] = 0.5

    @classmethod
    def longest_common(cls, value: str, text: str) -> Optional[Tuple[str, int]]:
        value_length: int = len(value)
        k_max: int = value_length - 1
        if k_max < 1:
            return None

        k_min: int = min(math.ceil(cls.MIN_COVERAGE * value_length), k_max)
        best: Optional[Tuple[str, int]] = cls._best_piece_of_size(value, text, k_min)
        if best is None:
            return None

        low, high = k_min, k_max
        while low < high:
            mid: int = (low + high + 1) // 2
            candidate: Optional[Tuple[str, int]] = cls._best_piece_of_size(value, text, mid)
            if candidate is None:
                high = mid - 1
                continue
            best = candidate
            low = mid
        return best

    @staticmethod
    def _best_piece_of_size(value: str, text: str, size: int) -> Optional[Tuple[str, int]]:
        for offset in range(len(value) - size + 1):
            piece: str = value[offset:offset + size]
            if piece in text:
                return piece, offset
        return None
