from pathlib import Path
from typing import ClassVar, Dict, Optional, Set

from har_reproducer.models import Extractor
from har_reproducer.reproduction import ExtractorMetadataStore, ExtractorRunner
from har_reproducer.replay.curl_dependency_parser import CurlDependencyParser
from har_reproducer.session import SessionStore


class ReplayTokenResolver:
    STATIC_CONFIRMATION_THRESHOLD: ClassVar[int] = 5

    def __init__(
            self,
            session_store: SessionStore,
            extractor_runner: ExtractorRunner,
            dependency_parser: CurlDependencyParser,
            metadata_store: ExtractorMetadataStore,
    ) -> None:
        self.session_store: SessionStore = session_store
        self.extractor_runner: ExtractorRunner = extractor_runner
        self.dependency_parser: CurlDependencyParser = dependency_parser
        self.metadata_store: ExtractorMetadataStore = metadata_store

    def resolve(
            self,
            curl_text: str,
            schedule: Set[int],
            replay_run_dir: Path,
            res_refer_dir: Path,
            original_responses_dir: Path,
    ) -> Set[str]:
        dependencies: Dict[str, int] = self.dependency_parser.parse(curl_text)
        token_ids: Set[str] = set(SessionStore.TOKEN_PLACEHOLDER_PATTERN.findall(curl_text))
        static_token_ids: Set[str] = set()
        for token_id in token_ids:
            if self._resolve_one(token_id, dependencies, schedule, replay_run_dir, res_refer_dir, original_responses_dir):
                static_token_ids.add(token_id)
        return static_token_ids

    def _resolve_one(
            self,
            token_id: str,
            dependencies: Dict[str, int],
            schedule: Set[int],
            replay_run_dir: Path,
            res_refer_dir: Path,
            original_responses_dir: Path,
    ) -> bool:
        origin_step: Optional[int] = dependencies.get(token_id)
        if origin_step in schedule:
            override_dir: Path = replay_run_dir
        else:
            override_dir = self._reference_dir_for_step(origin_step, res_refer_dir, original_responses_dir)
        value: Optional[str] = self.extractor_runner.run_existing(token_id, override_dir)
        if value is None:
            print(f"Failed to resolve token '{token_id}' during replay: extractor returned no value.")
            return False
        self.session_store.set_token(token_id, value)
        return self._record_observation(token_id, value)

    @staticmethod
    def _reference_dir_for_step(
            origin_step: Optional[int],
            res_refer_dir: Path,
            original_responses_dir: Path,
    ) -> Path:
        if origin_step is None:
            return res_refer_dir
        if (res_refer_dir / f"res_{origin_step:04d}.json").exists():
            return res_refer_dir
        return original_responses_dir

    def _record_observation(self, token_id: str, value: str) -> bool:
        persisted: Optional[Extractor] = self.metadata_store.load(token_id)
        if persisted is None:
            return False
        if persisted.last_value is None or persisted.last_value == value:
            persisted.valid_count += 1
        else:
            persisted.ever_changed = True
        persisted.last_value = value
        self.metadata_store.save(persisted)
        return not persisted.ever_changed and persisted.valid_count >= self.STATIC_CONFIRMATION_THRESHOLD
