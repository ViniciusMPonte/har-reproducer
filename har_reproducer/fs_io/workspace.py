from pathlib import Path

from har_reproducer.fs_io.workspace_dir import WorkspaceDir


class Workspace:

    def __init__(self, output_dir: Path) -> None:
        self.output_dir: Path = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.curls: Path = self._prepare_dir(WorkspaceDir.CURLS)
        self.real_responses: Path = self._prepare_dir(WorkspaceDir.REAL_RESPONSES)
        self.original_responses: Path = self._prepare_dir(WorkspaceDir.ORIGINAL_RESPONSES)
        self.real_requests: Path = self._prepare_dir(WorkspaceDir.REAL_REQUESTS)
        self.extractors: Path = self._prepare_dir(WorkspaceDir.EXTRACTORS)
        self.temp_extractors: Path = self._prepare_dir(WorkspaceDir.TEMP_EXTRACTORS)
        self.mitm_capture: Path = self._prepare_dir(WorkspaceDir.MITM_CAPTURE)
        self.replays: Path = self._prepare_dir(WorkspaceDir.REPLAYS)

    def _prepare_dir(self, workspace_dir: WorkspaceDir) -> Path:
        path: Path = self.output_dir / workspace_dir.value
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def get_root_path() -> Path:
        return Path(__file__).resolve().parent.parent

    @staticmethod
    def get_mitmproxy_ca_path() -> Path:
        return Workspace.get_root_path().parent / ".mitmproxy"

    def temp_extractor_file(self, safe_token_id: str) -> Path:
        return self.temp_extractors / f"temp_extractor_{safe_token_id}.py"

    def extractor_file(self, safe_token_id: str) -> Path:
        return self.extractors / f"extract_{safe_token_id}.py"

    def extractor_meta_file(self, safe_token_id: str) -> Path:
        return self.extractors / f"extract_{safe_token_id}.meta.json"

    def request_file(self, index: int) -> Path:
        return self.real_requests / f"req_{index:04d}.json"

    def response_file(self, index: int) -> Path:
        return self.real_responses / f"res_{index:04d}.json"

    def original_response_file(self, index: int) -> Path:
        return self.original_responses / f"res_{index:04d}.json"

    def mitm_capture_file(self) -> Path:
        return self.mitm_capture / "capture.har"

    def mitm_log_file(self) -> Path:
        return self.mitm_capture / "mitmdump.log"

    def curl_file(self, index: int) -> Path:
        return self.curls / f"req_{index:04d}.curl.sh"

    def replay_run_dir(self, run_id: str) -> Path:
        path: Path = self.replays / run_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def replay_response_file(self, run_id: str, index: int) -> Path:
        return self.replay_run_dir(run_id) / f"res_{index:04d}.json"
