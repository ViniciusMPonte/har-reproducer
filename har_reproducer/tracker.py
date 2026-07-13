import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Type

from .agents.base import BaseAgent
from .agents.cookie_agent import CookieAgent
from .agents.css_agent import CSSAgent
from .agents.header_agent import HeaderAgent
from .agents.jsonpath_agent import JSONPathAgent
from .agents.regex_agent import RegexAgent
from .grep_utils import grep_in_real_responses
from .models import (
    AgentType,
    Extractor,
    Step,
    StepRequest,
    DynamicToken,
    TokenLocation,
    StepAnalysis,
)
from .session import SessionStore


class TokenTracker:
    """
    The Analysis Pipeline: Detects dynamic tokens and determines how to extract them.
    """

    def __init__(self, responses_dir: Path, session_store: SessionStore) -> None:
        self.responses_dir: Path = responses_dir
        self.session_store: SessionStore = session_store

    def analyze_step(self, step: Step, baseline_step: Step, is_dry_run: bool = False) -> StepAnalysis:
        diffs: Dict[str, str] = self._compare_to_baseline(step, baseline_step)
        candidates: List[DynamicToken] = self._detect_candidates(diffs)
        resolved_tokens: List[DynamicToken] = self._resolve_candidates(candidates, is_dry_run)
        template: str = self._generate_curl_template(step.request)
        static_values: Dict[str, str] = self._extract_static_values(step, baseline_step)
        return self._build_step_analysis(step, static_values, resolved_tokens, template)

    def _resolve_candidates(
            self, candidates: List[DynamicToken], is_dry_run: bool
    ) -> List[DynamicToken]:
        return [self._process_candidate(candidate, is_dry_run) for candidate in candidates]

    def _build_step_analysis(
            self,
            step: Step,
            static_values: Dict[str, str],
            resolved_tokens: List[DynamicToken],
            template: str,
    ) -> StepAnalysis:
        return StepAnalysis(
            step_index=step.index,
            static_values=static_values,
            dynamic_tokens=resolved_tokens,
            curl_template=template,
        )

    def _process_candidate(self, candidate: DynamicToken, is_dry_run: bool) -> DynamicToken:
        existing: Optional[Extractor] = self.session_store.state.registry.get(candidate.token_id)
        if existing is not None and existing.verified:
            candidate.status = "Resolved"
            return candidate

        origin: Optional[Tuple[int, str]] = grep_in_real_responses(
            self.responses_dir, candidate.current_value
        )
        if not origin:
            candidate.status = "Unresolved"
            return candidate

        candidate.origin_step = origin[0]
        candidate.status = "Resolved" #Esse status esta errado, o certo seria só passar resolved quando extrator estivesse pronto. Talvez precise de outro status para esse caso

        response_sample: Optional[Dict[str, Any]] = self._load_response(candidate.origin_step)
        if response_sample is None:
            return candidate

        candidate.origin_location = self._find_origin_location(candidate.current_value, response_sample)

        self._register_extractor(candidate, response_sample, is_dry_run)
        return candidate

    def _register_extractor(
            self,
            candidate: DynamicToken,
            response_sample: Dict[str, Any],
            is_dry_run: bool,
    ) -> None:
        if is_dry_run:
            self.session_store.state.registry[candidate.token_id] = Extractor(
                token_id=candidate.token_id,
                code="",
                verified=False,
                agent_type=AgentType.REGEX,  # placeholder; not yet determined
            )
            return

        new_extractor: Optional[Extractor] = self._generate_extractor(candidate, response_sample)
        if new_extractor is not None:
            self.session_store.state.registry[candidate.token_id] = new_extractor

    def _load_response(self, step_index: int) -> Optional[Dict[str, Any]]:
        res_file: Path = self.responses_dir / f"res_{step_index:04d}.json"
        if not res_file.exists():
            return None
        try:
            data: Dict[str, Any] = json.loads(res_file.read_text(encoding="utf-8"))
            return data
        except Exception as e:
            print(f"[AVISO] Falha ao carregar response do step {step_index}: {e}")
            return None

    def _find_origin_location(self, value: str, response_sample: Dict[str, Any]) -> TokenLocation:
        for header_val in response_sample.get("headers", {}).values():
            if value in header_val:
                return TokenLocation.HEADER

        for cookie_val in response_sample.get("cookies", {}).values():
            if value in cookie_val:
                return TokenLocation.COOKIE

        return TokenLocation.BODY_JSON

    def _generate_extractor(self, candidate: DynamicToken, response_sample: Dict[str, Any]) -> Optional[Extractor]:
        location_map: Dict[TokenLocation, Type[BaseAgent]] = {
            TokenLocation.COOKIE: CookieAgent,
            TokenLocation.HEADER: HeaderAgent,
            TokenLocation.BODY_JSON: JSONPathAgent,
            TokenLocation.BODY_HTML: CSSAgent,
            TokenLocation.SCRIPT: RegexAgent,
        }

        agent_cls: Type[BaseAgent] = location_map.get(candidate.origin_location, RegexAgent)

        agent: BaseAgent = agent_cls(
            token_id=candidate.token_id,
            response_sample=response_sample,
            expected_value=candidate.current_value,
        )
        return agent.run_tdd_loop(origin_step=candidate.origin_step)

    def _compare_to_baseline(self, step: Step, baseline: Step) -> Dict[str, str]:
        diffs: Dict[str, str] = {}

        for k, v in step.request.headers.items():
            if baseline.request.headers.get(k) != v:
                diffs[f"header:{k}"] = v

        for k, v in step.request.cookies.items():
            if baseline.request.cookies.get(k) != v:
                diffs[f"cookie:{k}"] = v

        if step.request.body and baseline.request.body and step.request.body != baseline.request.body:
            body_val: Optional[str | bytes] = step.request.body
            diffs["body"] = (
                body_val
                if isinstance(body_val, str)
                else body_val.decode("utf-8", errors="replace")
            )

        return diffs

    def _detect_candidates(self, diffs: Dict[str, str]) -> List[DynamicToken]:
        candidates: List[DynamicToken] = []
        for path, value in diffs.items():

            token_id: str = path + value
            location: TokenLocation = self._determine_location(path)

            candidates.append(DynamicToken(
                token_id=token_id,
                current_value=str(value),
                destination_location=location,
                origin_step=None,
                status="Unresolved",
            ))

        return candidates

    def _determine_location(self, path: str) -> TokenLocation:
        if path.startswith("header:"):
            return TokenLocation.HEADER
        if path.startswith("cookie:"):
            return TokenLocation.COOKIE
        return TokenLocation.BODY_JSON

    def _generate_curl_template(self, request: StepRequest) -> str:
        headers_str: str = " ".join(
            [f'-H "{k}: {v}"' for k, v in request.headers.items()]
        )
        return f"curl -X {request.method} '{request.url}' {headers_str}"

    def _extract_static_values(self, step: Step, baseline: Step) -> Dict[str, str]:
        statics: Dict[str, str] = {}
        for k, v in step.request.headers.items():
            if baseline.request.headers.get(k) == v:
                statics[f"header:{k}"] = v
        return statics
