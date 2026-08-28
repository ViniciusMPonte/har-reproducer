from pathlib import Path
from typing import Any, ClassVar, Dict, List, Optional

from har_reproducer.contracts import HttpTransport
from har_reproducer.fs_io import HARParser, Workspace
from har_reproducer.models import Step, StepRequest, StepResponse, SuccessCriterion
from har_reproducer.replay.replay_result_comparator import ReplayResultComparator
from har_reproducer.reproduction import CookieJarCurlOverride, RequestUrlScope, StepRetryPolicy, StepSkipEvaluator
from har_reproducer.session import CookieJar, SessionStore
from har_reproducer.templates import ExtractorTemplate
from har_reproducer.tracking import TokenResolver, TokenTracker
from har_reproducer.validation import Validator


class Engine:
    USES_NETWORK: ClassVar[bool] = True

    def __init__(
            self,
            har_path: Path,
            workspace: Workspace,
            session_store: SessionStore,
            tracker: TokenTracker,
            token_resolver: TokenResolver,
            skip_evaluator: StepSkipEvaluator,
            retry_policy: StepRetryPolicy,
            validator: Validator,
            comparator: ReplayResultComparator,
            success_criteria: List[SuccessCriterion],
            http_transport: Optional[HttpTransport],
            cookie_jar: CookieJar,
            cookie_jar_curl_override: CookieJarCurlOverride,
    ) -> None:
        self.har_path: Path = har_path
        self.workspace: Workspace = workspace
        self.session_store: SessionStore = session_store
        self.tracker: TokenTracker = tracker
        self.token_resolver: TokenResolver = token_resolver
        self.skip_evaluator: StepSkipEvaluator = skip_evaluator
        self.retry_policy: StepRetryPolicy = retry_policy
        self.validator: Validator = validator
        self.comparator: ReplayResultComparator = comparator
        self.success_criteria: List[SuccessCriterion] = success_criteria
        self.http_transport: Optional[HttpTransport] = http_transport
        self.cookie_jar: CookieJar = cookie_jar
        self.cookie_jar_curl_override: CookieJarCurlOverride = cookie_jar_curl_override

    def run(self) -> bool:
        return self._reproduce()

    def _reproduce(self) -> bool:
        entries: List[Dict[str, Any]] = HARParser.get_entries(self.har_path)
        first_entry: Step = HARParser.parse_entry(entries[0], 0)
        self._warn_missing_response_bodies(entries)

        last_response: Optional[StepResponse] = None
        for index, entry in enumerate(entries):
            response: StepResponse = self._process_entry(index, entry, first_entry)
            if not response.skipped:
                last_response = response

        return self._validate_final(last_response)

    @staticmethod
    def _warn_missing_response_bodies(entries: List[Dict[str, Any]]) -> None:
        missing: int = HARParser.entries_missing_response_body(entries)
        if missing == 0:
            return

        print(
            f"WARNING: {missing} de {len(entries)} entries do HAR não têm corpo de resposta gravado "
            f"(excluídos os status 101/204/304, que normalmente não carregam corpo). Origens de token "
            f"que estejam nesses corpos são indescobríveis — regrave o HAR preservando o conteúdo das "
            f'respostas ("Preserve log" + export completo).'
        )

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
        self.workspace.request_file(index).write_text(request.model_dump_json(indent=2), encoding="utf-8")

    def _persist_original_response_step(self, index: int, response: Optional[StepResponse]) -> None:
        assert response is not None
        self.workspace.original_response_file(index).write_text(
            response.model_dump_json(indent=2), encoding="utf-8"
        )

    def _persist_response_step(self, index: int, response: StepResponse) -> None:
        self.workspace.response_file(index).write_text(response.model_dump_json(indent=2), encoding="utf-8")

    def _persist_template_curl(self, index: int, curl_template: str) -> None:
        self.workspace.curl_file(index).write_text(
            ExtractorTemplate.render_bash_script(curl_template), encoding="utf-8"
        )

    def _validate_final(self, last_response: Optional[StepResponse]) -> bool:
        if not last_response or not self.success_criteria:
            return True

        is_success: bool = self.validator.validate(last_response, self.success_criteria)
        print(f"\nFinal Validation Result: {'✓ SUCCESS' if is_success else '✗ FAILURE'}")
        return is_success

    def handle_recovery(self, step_index: int, response: StepResponse) -> bool:
        if not self.comparator.needs_recovery(step_index, response):
            return False

        print(
            f"Detected {response.status_code} (reference expects a different status). "
            f"Attempting deterministic recovery (token refresh)..."
        )
        self.token_resolver.resolve_all(force=True)
        return True

    def execute_step(self, step: Step) -> StepResponse:
        return self.retry_policy.execute(
            step.index, lambda: self._attempt_step(step), lambda response: self.handle_recovery(step.index, response)
        )

    def _attempt_step(self, step: Step) -> StepResponse:
        assert self.http_transport is not None
        curl_literal: str = self.session_store.render(step.analysis.curl_template)
        host, port, path = RequestUrlScope.parts(step.request.url)
        curl_with_jar: str = self.cookie_jar_curl_override.apply(curl_literal, host, port, path)
        response: StepResponse = self.http_transport.send_request(curl_with_jar, step.index)
        self.cookie_jar.feed(host, port, response.cookies, response.cookie_attributes)
        return response
