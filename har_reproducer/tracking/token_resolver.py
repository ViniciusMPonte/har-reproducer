from typing import Optional

from har_reproducer.fs_io import Workspace
from har_reproducer.models import Extractor
from har_reproducer.reproduction import ExtractorRunner
from har_reproducer.session import SessionStore


class TokenResolver:
    def __init__(self, session_store: SessionStore) -> None:
        self.session_store: SessionStore = session_store
        self.extractor_runner: ExtractorRunner = ExtractorRunner()

    def resolve_all(self) -> None:
        for token_id, extractor in self.session_store.state.registry.items():
            if self._should_refresh_token(extractor):
                self._refresh_token(token_id, extractor)

    def _should_refresh_token(self, extractor: Extractor) -> bool:
        return extractor.verified and extractor.origin_step is not None

    def _refresh_token(self, token_id: str, extractor: Extractor) -> None:
        if not Workspace.response_file(extractor.origin_step).exists():
            return

        try:
            value: Optional[str] = self.extractor_runner.run(extractor)
        except Exception as e:
            print(f"Failed to refresh token '{token_id}': {e}")
            return

        if value:
            self.session_store.set_token(token_id, value)
