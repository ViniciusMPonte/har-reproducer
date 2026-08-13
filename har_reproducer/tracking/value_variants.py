import base64
import urllib.parse
from typing import List, Set


class ValueVariants:

    @staticmethod
    def try_decode(value: str) -> str:
        current: str = value

        decoded_url: str = urllib.parse.unquote(current)
        if decoded_url != current:
            current = decoded_url

        try:
            b64_bytes: bytes = base64.b64decode(current, validate=True)
            decoded_b64: str = b64_bytes.decode("utf-8")
            if decoded_b64.isprintable():
                current = decoded_b64
        except Exception:
            pass

        return current

    @classmethod
    def of(cls, value: str) -> List[str]:
        candidates: List[str] = [
            value,
            cls.try_decode(value),
            urllib.parse.quote(value, safe=""),
            base64.b64encode(value.encode("utf-8")).decode("ascii"),
        ]
        return cls._deduplicate(candidates)

    @staticmethod
    def _deduplicate(values: List[str]) -> List[str]:
        seen: Set[str] = set()
        unique: List[str] = []
        for value in values:
            if value and value not in seen:
                seen.add(value)
                unique.append(value)
        return unique
