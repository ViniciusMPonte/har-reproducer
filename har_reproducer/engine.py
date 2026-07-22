import json
import subprocess
import sys
from pathlib import Path
from subprocess import CompletedProcess
from typing import Any, Dict, List, Optional, Tuple

import httpx
from httpx import Response
from pydantic import TypeAdapter

from .agents.diagnose_agent import DiagnoseAgent
from .curl_generator import CurlGenerator
from .llm_factory import create_llm
from .models import (
    DynamicToken,
    Extractor,
    FailureContext,
    Patch,
    ProjectConfig,
    Step,
    StepAnalysis,
    StepRequest,
    StepResponse,
    SuccessCriterion,
)
from .parser import HARParser
from .session import SessionStore
from .templates import ExtractorTemplate
from .tracker import TokenTracker
from .validator import Validator


class Engine:

    def __init__(
            self,
            har_path: Path,
            output_dir: Path,
            config_path: Optional[Path] = None,
    ) -> None:
        self.har_path: Path = har_path
        self.output_dir: Path = output_dir
        self.curls_dir: Path = output_dir / "curls"
        self.curls_dir.mkdir(parents=True, exist_ok=True)
        self.real_responses_dir: Path = output_dir / "real_responses"
        self.real_responses_dir.mkdir(parents=True, exist_ok=True)
        self.real_requests_dir: Path = output_dir / "real_requests"
        self.real_requests_dir.mkdir(parents=True, exist_ok=True)
        self.extractors_dir: Path = output_dir / "extractors"
        self.extractors_dir.mkdir(parents=True, exist_ok=True)

        self.session_store: SessionStore = SessionStore()
        self.validator: Validator = Validator()

        self.success_criteria: List[SuccessCriterion] = []
        llm = None

        if config_path and config_path.exists():
            try:
                with open(config_path, "r") as f:
                    config_data: Any = json.load(f)
                    _project_config_adapter: TypeAdapter[ProjectConfig] = TypeAdapter(ProjectConfig)
                    project_config = _project_config_adapter.validate_python(config_data)
                    self.success_criteria = project_config.success_criteria
                    if project_config.llm:
                        llm = create_llm(project_config.llm)
                        print(
                            f"LLM fallback enabled from config: provider={project_config.llm.provider} model={project_config.llm.model}")
            except Exception as e:
                import traceback
                traceback.print_exc()
                print(f"Error loading config: {e}")

        self.tracker: TokenTracker = TokenTracker(self.real_responses_dir, self.session_store, llm=llm)

    def run(self) -> bool:
        entries: List[Dict[str, Any]] = HARParser.get_entries(self.har_path)
        first_entry: Step = HARParser.parse_entry(entries[0], 0)

        analyses: List[StepAnalysis] = []
        last_response: Optional[StepResponse] = None
        for index, entry in enumerate(entries):
            step: Step = HARParser.parse_entry(entry, index)

            step_analysis: StepAnalysis = self.tracker.analyze_step(step, first_entry, is_dry_run=False)
            analyses.append(step_analysis)

            self.update_session_tokens()

            final_request: StepRequest
            response: StepResponse
            final_request, response = self.execute_step(step)

            last_response = response

            req_file: Path = self.real_requests_dir / f"req_{index:04d}.json"
            req_file.write_text(final_request.model_dump_json(indent=2), encoding="utf-8")

            res_file: Path = self.real_responses_dir / f"res_{index:04d}.json"
            res_file.write_text(response.model_dump_json(indent=2), encoding="utf-8")

            print(f"Step {index} completed with status {response.status_code}")

        if last_response and self.success_criteria:
            is_success: bool = self.validator.validate(last_response, self.success_criteria)
            print(f"\nFinal Validation Result: {'✓ SUCCESS' if is_success else '✗ FAILURE'}")
            return is_success

        return True

    def dry_run(self) -> None:
        entries: List[Dict[str, Any]] = HARParser.get_entries(self.har_path)
        first_entry: Step = HARParser.parse_entry(entries[0], 0)

        analyses: List[StepAnalysis] = []
        for index, entry in enumerate(entries):
            step: Step = HARParser.parse_entry(entry, index)

            self.update_session_tokens()

            print(f"Dry-run: Analyzing step {index}...")
            analysis: StepAnalysis = self.tracker.analyze_step(step, first_entry, is_dry_run=True)
            analyses.append(analysis)

        self._generate_dry_run_report(analyses)

    def _generate_dry_run_report(self, analyses: List[StepAnalysis]) -> None:
        print("\n--- Dry-Run Analysis Report ---")
        print(f"Analyzed {len(analyses)} steps.")

        all_tokens: Dict[str, DynamicToken] = {}
        for analysis in analyses:
            for token in analysis.dynamic_tokens:
                all_tokens[token.token_id] = token

        print(f"Detected {len(all_tokens)} dynamic token candidates:")
        for tid, token in all_tokens.items():
            status_label: str = "✓ Resolved" if token.status == "Resolved" else "✗ Unresolved"
            origin_label: str = f" at step {token.origin_step}" if token.origin_step is not None else ""
            print(f"- {tid}: {status_label}{origin_label} (Location: {token.destination_location})")
        print("------------------------------\n")

    def update_session_tokens(self) -> None:
        for token_id, extractor in self.session_store.state.registry.items():
            if not extractor.verified or extractor.origin_step is None:
                continue

            res_file: Path = self.real_responses_dir / f"res_{extractor.origin_step:04d}.json"
            if res_file.exists():
                try:
                    response: Dict[str, Any] = json.loads(res_file.read_text(encoding="utf-8"))
                    value: Optional[str] = self._run_extractor(extractor, response)
                    if value:
                        self.session_store.set_token(token_id, value)
                except Exception:
                    continue

    def _run_extractor(self, extractor: Extractor, response: Dict[str, Any]) -> Optional[str]:
        safe_token_id: str = extractor.token_id
        extractor_file: Path = self.extractors_dir / f"extract_{safe_token_id}.py"

        wrapped_code: str = ExtractorTemplate.render_script(
            safe_token_id=safe_token_id,
            code=extractor.code,
            response_sample=response,
        )
        extractor_file.write_text(wrapped_code, encoding="utf-8")

        try:
            result: CompletedProcess[str] = subprocess.run(
                [sys.executable, str(extractor_file)],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return None

    def handle_recovery(self, response: StepResponse) -> bool:
        if response.status_code == 401:
            print("Detected 401 Unauthorized. Attempting deterministic recovery (token refresh)...")
            self.update_session_tokens()
            return True

        if response.status_code == 400:
            print("Detected 400 Bad Request. Attempting deterministic recovery (token refresh)...")
            self.update_session_tokens()
            return True

        return False

    def diagnose(self, step_index: int) -> Optional[Patch]:
        """
        Launches the Diagnostic Agent to find a fix for a failed step.

        Returns a Patch describing the proposed fix, or None if no fix was found.
        The caller is responsible for deciding whether and how to apply the patch.

        # TODO (TASK-10): The diagnose → apply flow is not production-ready.
        """
        ctx: FailureContext = FailureContext(
            failed_step=step_index,
            request_attempted=StepRequest(url="dummy", method="GET"),
            response_received=StepResponse(status_code=401, headers={}, cookies={}, body="Unauthorized"),
            session_snapshot=self.session_store.state,
            active_extractors=list(self.session_store.state.registry.values()),
        )

        agent: DiagnoseAgent = DiagnoseAgent(self, ctx)
        return agent.diagnose()

    def execute_step(self, step: Step) -> Tuple[StepRequest, StepResponse]:
        max_attempts: int = 2
        for attempt in range(max_attempts):
            req: StepRequest = step.request

            raw_headers: Dict[str, str] = self.session_store.render_dict(req.headers)
            headers: Dict[str, str] = {k: v for k, v in raw_headers.items() if not k.startswith(":")}
            cookies: Dict[str, str] = self.session_store.render_dict(req.cookies)

            body: Optional[str]
            if req.body is None:
                body = None
            elif isinstance(req.body, bytes):
                body = req.body.decode("utf-8", errors="replace")
            else:
                body = self.session_store.render(req.body)

            final_request: StepRequest = StepRequest(
                url=req.url,
                method=req.method,
                headers=headers,
                cookies=cookies,
                body=body,
                is_skippable=req.is_skippable,
            )

            curl_cmd: str = CurlGenerator().generate(
                step.index, final_request, session_store=self.session_store
            )

            curl_file: Path = self.curls_dir / f"req_{step.index:04d}.curl.sh"
            curl_file.write_text(f"#!/bin/bash\n{curl_cmd}\n", encoding="utf-8")

            with httpx.Client(follow_redirects=False) as client:
                resp: Response = client.request(
                    method=final_request.method,
                    url=final_request.url,
                    headers=final_request.headers,
                    cookies=final_request.cookies,
                    content=(
                        final_request.body.encode("utf-8")
                        if isinstance(final_request.body, str)
                        else final_request.body
                    ) if final_request.body else None,
                )

                raw_status: int = resp.status_code
                status_code: int
                if not isinstance(raw_status, int):
                    try:
                        status_code = int(raw_status)
                    except (TypeError, ValueError):
                        status_code = raw_status.value if hasattr(raw_status, "value") else 500
                else:
                    status_code = raw_status

                response: StepResponse = StepResponse(
                    status_code=status_code,
                    headers=dict(resp.headers),
                    cookies=dict(client.cookies),
                    body=resp.text,
                    body_mime=resp.headers.get("Content-Type"),
                    redirect_url=resp.headers.get("Location"),
                )

            if attempt == 0 and self.handle_recovery(response):
                print(f"Deterministic recovery successful for step {step.index}. Retrying request...")
                continue

            return final_request, response

        raise RuntimeError(f"execute_step exhausted {max_attempts} attempts for step {step.index}")
