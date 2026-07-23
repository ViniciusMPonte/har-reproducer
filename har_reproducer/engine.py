import json
from pathlib import Path
from typing import Any, ClassVar, Dict, List, Optional, Set, Tuple

from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import TypeAdapter

from .contracts import StepExecutor
from .fs_io import HARParser, Workspace
from .llm_factory import LLMFactory
from .models import (
    Extractor,
    ProjectConfig,
    Step,
    StepRequest,
    StepResponse,
    SuccessCriterion,
)
from .reproduction import ExtractorRunner, HttpTransport, RequestBuilder
from .session import SessionStore
from .tracking import TokenTracker
from .validator import Validator


class Engine:
    RECOVERABLE_STATUS_CODES: ClassVar[Set[int]] = {400, 401}
    MAX_STEP_ATTEMPTS: ClassVar[int] = 2

    def __init__(
            self,
            har_path: Path,
            output_dir: Path,
            config_path: Optional[Path] = None,
    ) -> None:
        self.har_path: Path = har_path
        self.output_dir: Path = output_dir

        Workspace.init(output_dir)
        self.curls_dir: Path = Workspace.curls
        self.real_responses_dir: Path = Workspace.real_responses
        self.real_requests_dir: Path = Workspace.real_requests
        self.extractors_dir: Path = Workspace.extractors
        self.temp_extractors_dir: Path = Workspace.temp_extractors

        self.session_store: SessionStore = SessionStore()
        self.validator: Validator = Validator()

        self.request_builder: RequestBuilder = RequestBuilder(self.session_store, self.curls_dir)
        self.http_transport: HttpTransport = HttpTransport()
        self.extractor_runner: ExtractorRunner = ExtractorRunner()

        self.success_criteria, llm = self._load_project_config(config_path)
        self.tracker: TokenTracker = TokenTracker(self.real_responses_dir, self.session_store, llm=llm)

    def _load_project_config(
            self, config_path: Optional[Path]
    ) -> Tuple[List[SuccessCriterion], Optional[BaseChatModel]]:
        if not config_path or not config_path.exists():
            return [], None

        try:
            return self._parse_project_config(config_path)
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"Error loading config: {e}")
            return [], None

    def _parse_project_config(
            self, config_path: Path
    ) -> Tuple[List[SuccessCriterion], Optional[BaseChatModel]]:
        config_json: str = config_path.read_text(encoding="utf-8")
        adapter: TypeAdapter[ProjectConfig] = TypeAdapter(ProjectConfig)
        project_config: ProjectConfig = adapter.validate_json(config_json)

        llm: Optional[BaseChatModel] = self._build_llm(project_config)
        return project_config.success_criteria, llm

    def _build_llm(self, project_config: ProjectConfig) -> Optional[BaseChatModel]:
        if not project_config.llm:
            return None

        llm = LLMFactory.create(project_config.llm)
        print(
            f"LLM fallback enabled from config: "
            f"provider={project_config.llm.provider} model={project_config.llm.model}"
        )
        return llm

    def run(self) -> bool:
        return self._reproduce(self.execute_step)

    def dry_run(self) -> bool:
        return self._reproduce(self.execute_step_dry)

    def _reproduce(self, executor: StepExecutor) -> bool:
        entries: List[Dict[str, Any]] = HARParser.get_entries(self.har_path)
        first_entry: Step = HARParser.parse_entry(entries[0], 0)

        last_response: Optional[StepResponse] = None
        for index, entry in enumerate(entries):
            last_response = self._process_entry(index, entry, first_entry, executor)

        return self._validate_final(last_response)

    def _process_entry(
            self,
            index: int,
            entry: Dict[str, Any],
            first_entry: Step,
            executor: StepExecutor,
    ) -> StepResponse:
        step: Step = HARParser.parse_entry(entry, index)

        self.tracker.analyze_step(step, first_entry)
        self.update_session_tokens()

        final_request, response = executor(step)
        self._persist_step(index, final_request, response)
        print(f"Step {index} completed with status {response.status_code}")
        return response

    def _persist_step(self, index: int, request: StepRequest, response: StepResponse) -> None:
        req_file: Path = self.real_requests_dir / f"req_{index:04d}.json"
        req_file.write_text(request.model_dump_json(indent=2), encoding="utf-8")

        res_file: Path = self.real_responses_dir / f"res_{index:04d}.json"
        res_file.write_text(response.model_dump_json(indent=2), encoding="utf-8")

    def _validate_final(self, last_response: Optional[StepResponse]) -> bool:
        if not last_response or not self.success_criteria:
            return True

        is_success: bool = self.validator.validate(last_response, self.success_criteria)
        print(f"\nFinal Validation Result: {'✓ SUCCESS' if is_success else '✗ FAILURE'}")
        return is_success

    def update_session_tokens(self) -> None:
        for token_id, extractor in self.session_store.state.registry.items():
            if self._should_refresh_token(extractor):
                self._refresh_token(token_id, extractor)

    def _should_refresh_token(self, extractor: Extractor) -> bool:
        return extractor.verified and extractor.origin_step is not None

    def _refresh_token(self, token_id: str, extractor: Extractor) -> None:
        response: Optional[Dict[str, Any]] = self._load_step_response(extractor.origin_step)
        if response is None:
            return

        try:
            value: Optional[str] = self.extractor_runner.run(extractor, response)
        except Exception:
            return

        if value:
            self.session_store.set_token(token_id, value)

    def _load_step_response(self, step_index: int) -> Optional[Dict[str, Any]]:
        res_file: Path = self.real_responses_dir / f"res_{step_index:04d}.json"
        if not res_file.exists():
            return None

        try:
            return json.loads(res_file.read_text(encoding="utf-8"))
        except Exception:
            return None

    def handle_recovery(self, response: StepResponse) -> bool:
        if response.status_code not in self.RECOVERABLE_STATUS_CODES:
            return False

        print(
            f"Detected {response.status_code}. "
            f"Attempting deterministic recovery (token refresh)..."
        )
        self.update_session_tokens()
        return True

    def execute_step_dry(self, step: Step) -> Tuple[StepRequest, StepResponse]:
        final_request: StepRequest = self.request_builder.build_final_request(step)
        self.request_builder.write_curl(step, final_request)
        assert step.response is not None
        return final_request, step.response

    def execute_step(self, step: Step) -> Tuple[StepRequest, StepResponse]:
        for attempt in range(self.MAX_STEP_ATTEMPTS):
            final_request, response = self._attempt_step(step)

            is_last_attempt: bool = attempt == self.MAX_STEP_ATTEMPTS - 1
            if is_last_attempt or not self.handle_recovery(response):
                return final_request, response

            print(f"Deterministic recovery successful for step {step.index}. Retrying request...")

        raise RuntimeError(f"execute_step exhausted {self.MAX_STEP_ATTEMPTS} attempts for step {step.index}")

    def _attempt_step(self, step: Step) -> Tuple[StepRequest, StepResponse]:
        final_request: StepRequest = self.request_builder.build_final_request(step)
        self.request_builder.write_curl(step, final_request)
        response: StepResponse = self.http_transport.send_request(final_request, step.index)
        return final_request, response
