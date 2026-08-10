from typing import Dict, Optional

from har_reproducer.models import Extractor


class FakeMetadataStore:

    def __init__(self) -> None:
        self.saved: Dict[str, Extractor] = {}

    def load(self, token_id: str) -> Optional[Extractor]:
        return self.saved.get(token_id)

    def save(self, extractor: Extractor) -> None:
        self.saved[extractor.token_id] = extractor
