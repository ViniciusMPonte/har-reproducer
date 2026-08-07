from pathlib import Path
from typing import Any, ClassVar, Dict, List, Optional

from langchain_core.language_models.chat_models import BaseChatModel

from har_reproducer.agents import AgentFactory
from har_reproducer.config import ProjectConfigLoader
from har_reproducer.contracts import HttpTransport
from har_reproducer.fs_io import HARParser, Workspace
from har_reproducer.llm import LLMFactory
from har_reproducer.models import (
    ProjectConfig,
    Step,
    StepRequest,
    StepResponse,
    SuccessCriterion,
)
from har_reproducer.reproduction import (
    CurlGenerator,
    ExtractorMetadataStore,
    ExtractorRunner,
    StepRetryPolicy,
    StepSkipEvaluator,
)
from har_reproducer.session import SessionStore
from har_reproducer.templates import ExtractorTemplate
from har_reproducer.tracking import BaselineDiff, CandidateResolver, PlaceholderApplier, TokenResolver, TokenTracker
from har_reproducer.validation import Validator


class Engine:
    USES_NETWORK: ClassVar[bool] = True

    def __init__(
            self,
            har_path: Path,
            output_dir: Path,
            config_path: Optional[Path] = None,
            http_transport: Optional[HttpTransport] = None,
    ) -> None:
        self.har_path: Path = har_path
        self.output_dir: Path = output_dir

        Workspace.init(output_dir)
        self.curls_dir: Path = Workspace.curls
        self.original_responses_dir: Path = Workspace.original_responses
        self.tracking_responses_dir: Path = Workspace.real_responses if self.USES_NETWORK else Workspace.original_responses
        self.extractors_dir: Path = Workspace.extractors
        self.temp_extractors_dir: Path = Workspace.temp_extractors

        self.session_store: SessionStore = SessionStore()
        self.validator: Validator = Validator()
        self.retry_policy: StepRetryPolicy = StepRetryPolicy()
        extractor_runner: ExtractorRunner = ExtractorRunner()
        metadata_store: ExtractorMetadataStore = ExtractorMetadataStore()

        project_config: ProjectConfig = ProjectConfigLoader.load(config_path)

        self.skip_evaluator: StepSkipEvaluator = StepSkipEvaluator(project_config.skip_rules)

        self.http_transport: Optional[HttpTransport] = http_transport
        self.token_resolver: TokenResolver = TokenResolver(
            self.tracking_responses_dir, self.session_store, extractor_runner
        )

        self.success_criteria: List[SuccessCriterion] = project_config.success_criteria
        llm: Optional[BaseChatModel] = self._build_llm(project_config)
        agent_factory: AgentFactory = AgentFactory(llm)
        baseline_diff: BaselineDiff = BaselineDiff()
        candidate_resolver: CandidateResolver = CandidateResolver(
            self.tracking_responses_dir, self.session_store, extractor_runner, metadata_store, agent_factory
        )
        placeholder_applier: PlaceholderApplier = PlaceholderApplier(self.session_store)
        curl_generator: CurlGenerator = CurlGenerator()
        self.tracker: TokenTracker = TokenTracker(baseline_diff, candidate_resolver, placeholder_applier, curl_generator)

    def _build_llm(self, project_config: ProjectConfig) -> Optional[BaseChatModel]:
        if not project_config.llm:
            return None

        llm: BaseChatModel = LLMFactory.create(project_config.llm)
        print(
            f"LLM fallback enabled from config: "
            f"provider={project_config.llm.provider} model={project_config.llm.model}"
        )
        return llm

    def run(self) -> bool:
        return self._reproduce()

    def _reproduce(self) -> bool:
        entries: List[Dict[str, Any]] = HARParser.get_entries(self.har_path)
        first_entry: Step = HARParser.parse_entry(entries[0], 0)

        last_response: Optional[StepResponse] = None
        for index, entry in enumerate(entries):
            response: StepResponse = self._process_entry(index, entry, first_entry)
            if not response.skipped:
                last_response = response

        return self._validate_final(last_response)

    def _process_entry(
            self,
            index: int,
            entry: Dict[str, Any],
            first_entry: Step,
    ) -> StepResponse:
        step: Step = HARParser.parse_entry(entry, index)
        skip_reason: Optional[str] = self.skip_evaluator.skip_reason(step.request)
        step.request.is_skippable = skip_reason is not None

        self._persist_request_step(index, step.request)
        self._persist_original_response_step(index, step.response)

        if skip_reason is not None:
            return self._skip_entry(index, skip_reason)

        step.analysis = self.tracker.analyze_step(step, first_entry)
        if self.USES_NETWORK:
            self.token_resolver.resolve_all()

        response: StepResponse = self.execute_step(step)
        self._persist_response_step(index, response)
        print(f"Step {index} completed with status {response.status_code}")

        if response.status_code != 0:
            self._persist_template_curl(index, step.analysis.curl_template)

        return response

    def _skip_entry(self, index: int, reason: str) -> StepResponse:
        response: StepResponse = StepResponse(status_code=0, skipped=True, skip_reason=reason)
        self._persist_response_step(index, response)
        print(f"Step {index} skipped ({reason})")
        return response

    def _persist_request_step(self, index: int, request: StepRequest) -> None:
        Workspace.request_file(index).write_text(request.model_dump_json(indent=2), encoding="utf-8")

    def _persist_original_response_step(self, index: int, response: Optional[StepResponse]) -> None:
        assert response is not None
        Workspace.original_response_file(index).write_text(response.model_dump_json(indent=2), encoding="utf-8")

    def _persist_response_step(self, index: int, response: StepResponse) -> None:
        Workspace.response_file(index).write_text(response.model_dump_json(indent=2), encoding="utf-8")

    def _persist_template_curl(self, index: int, curl_template: str) -> None:
        Workspace.curl_file(index).write_text(ExtractorTemplate.render_bash_script(curl_template), encoding="utf-8")

    def _validate_final(self, last_response: Optional[StepResponse]) -> bool:
        if not last_response or not self.success_criteria:
            return True

        is_success: bool = self.validator.validate(last_response, self.success_criteria)
        print(f"\nFinal Validation Result: {'✓ SUCCESS' if is_success else '✗ FAILURE'}")
        return is_success

    def handle_recovery(self, response: StepResponse) -> bool:
        if response.status_code not in self.retry_policy.RECOVERABLE_STATUS_CODES:
            return False

        print(
            f"Detected {response.status_code}. "
            f"Attempting deterministic recovery (token refresh)..."
        )
        self.token_resolver.resolve_all(force=True)
        return True

    def execute_step(self, step: Step) -> StepResponse:
        return self.retry_policy.execute(step.index, lambda: self._attempt_step(step), self.handle_recovery)

    def _attempt_step(self, step: Step) -> StepResponse:
        assert self.http_transport is not None
        curl_literal: str = self.session_store.render(step.analysis.curl_template)
        response: StepResponse = self.http_transport.send_request(curl_literal, step.index)
        return response
