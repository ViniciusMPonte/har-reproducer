from typing import Dict, Optional
from urllib.parse import ParseResult, urlparse


class FlowVocabulary:

    def __init__(self) -> None:
        self._first_seen: Dict[str, int] = {}

    def observe(self, url: str, step_index: int) -> None:
        parsed: ParseResult = urlparse(url)
        if not parsed.hostname:
            return

        for address in (parsed.hostname, parsed.netloc, f"{parsed.scheme}://{parsed.netloc}"):
            self._first_seen.setdefault(address, step_index)

    def rejects(self, matched_text: str, origin_step: int) -> bool:
        first_seen: Optional[int] = self._first_seen.get(matched_text)
        return first_seen is not None and first_seen < origin_step
