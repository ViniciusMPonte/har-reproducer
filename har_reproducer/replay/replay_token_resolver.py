from pathlib import Path
from typing import Dict, Optional, Set

from har_reproducer.reproduction import ExtractorRunner
from har_reproducer.replay.curl_dependency_parser import CurlDependencyParser
from har_reproducer.session import SessionStore


class ReplayTokenResolver:
    def __init__(
            self,
            session_store: SessionStore,
            extractor_runner: ExtractorRunner,
            dependency_parser: CurlDependencyParser,
    ) -> None:
        self.session_store: SessionStore = session_store
        self.extractor_runner: ExtractorRunner = extractor_runner
        self.dependency_parser: CurlDependencyParser = dependency_parser

    def resolve(
            self,
            curl_text: str,
            schedule: Set[int],
            replay_run_dir: Path,
            res_refer_dir: Path,
    ) -> None:
        dependencies: Dict[str, int] = self.dependency_parser.parse(curl_text)
        token_ids: Set[str] = set(SessionStore.TOKEN_PLACEHOLDER_PATTERN.findall(curl_text))
        for token_id in token_ids:
            self._resolve_one(token_id, dependencies, schedule, replay_run_dir, res_refer_dir)

    def _resolve_one(
            self,
            token_id: str,
            dependencies: Dict[str, int],
            schedule: Set[int],
            replay_run_dir: Path,
            res_refer_dir: Path,
    ) -> None:
        origin_step: Optional[int] = dependencies.get(token_id)
        override_dir: Path = replay_run_dir if origin_step in schedule else res_refer_dir
        value: Optional[str] = self.extractor_runner.run_existing(token_id, override_dir)
        if value is None:
            print(f"Failed to resolve token '{token_id}' during replay: extractor returned no value.")
            return
        self.session_store.set_token(token_id, value)
