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
        self.responses_dir = responses_dir
        self.session_store = session_store

    def analyze_step(self, step: Step, baseline_step: Step, is_dry_run: bool = False) -> StepAnalysis:
        """Runs the 8-stage pipeline to analyze a step."""
        # 1. Baseline Comparison
        diffs: Dict[str, str] = self._compare_to_baseline(step, baseline_step)

        # 2. Dynamic Candidate Detection
        candidates: List[DynamicToken] = self._detect_candidates(diffs)

        # 3. Origin Search (Grep)
        resolved_tokens: List[DynamicToken] = []
        for candidate in candidates:
            # 4. Extractor Identification / Reuse
            if candidate.token_id in self.session_store.state.registry:
                existing: Extractor = self.session_store.state.registry[candidate.token_id]
                if existing.verified:
                    candidate.status = "Resolved"
                    resolved_tokens.append(candidate)
                    continue

            origin: Optional[Tuple[int, str]] = grep_in_real_responses(
                self.responses_dir, candidate.current_value
            )
            if origin:
                candidate.origin_step = origin[0]
                candidate.status = "Resolved"
                resolved_tokens.append(candidate)

                response_sample: Optional[Dict[str, Any]] = self._load_response(candidate.origin_step)
                if response_sample:
                    if not is_dry_run:
                        # 5. Extractor Generation
                        new_extractor: Optional[Extractor] = self._generate_extractor(
                            candidate, response_sample
                        )
                        if new_extractor is not None:
                            self.session_store.state.registry[candidate.token_id] = new_extractor
                    else:
                        # In dry-run, register as Pending (no code generation)
                        self.session_store.state.registry[candidate.token_id] = Extractor(
                            token_id=candidate.token_id,
                            code="",
                            verified=False,
                            agent_type=AgentType.REGEX,  # placeholder; not yet determined
                        )
            else:
                candidate.status = "Unresolved"
                resolved_tokens.append(candidate)

        # 6. Curl Template Generation
        template: str = self._generate_curl_template(step.request)

        # 8. StepAnalysis construction
        return StepAnalysis(
            step_index=step.index,
            static_values=self._extract_static_values(step, baseline_step),
            dynamic_tokens=resolved_tokens,
            curl_template=template,
        )

    def _load_response(self, step_index: int) -> Optional[Dict[str, Any]]:
        """Loads a response JSON file from the responses directory."""
        res_file = self.responses_dir / f"res_{step_index:04d}.json"
        if res_file.exists():
            try:
                data: Dict[str, Any] = json.loads(res_file.read_text(encoding="utf-8"))
                return data
            except Exception as e:
                print(f"[AVISO] Falha ao carregar response do step {step_index}: {e}")
                return None
        return None

    def _generate_extractor(self, candidate: DynamicToken, response_sample: Dict[str, Any]) -> Optional[Extractor]:
        """Tries to generate a verified extractor using the appropriate agent."""
        location_map: Dict[TokenLocation, Type[BaseAgent]] = {
            TokenLocation.COOKIE: CookieAgent,
            TokenLocation.HEADER: HeaderAgent,
            TokenLocation.BODY_JSON: JSONPathAgent,
            TokenLocation.BODY_HTML: CSSAgent,
            TokenLocation.SCRIPT: RegexAgent,
        }
        agent_cls: Type[BaseAgent] = location_map.get(candidate.location, RegexAgent)

        agent: BaseAgent = agent_cls(
            token_id=candidate.token_id,
            response_sample=response_sample,
            expected_value=candidate.current_value,
        )
        return agent.run_tdd_loop(origin_step=candidate.origin_step)

    def _compare_to_baseline(self, step: Step, baseline: Step) -> Dict[str, str]:
        """Detects values that differ from the baseline."""
        diffs: Dict[str, str] = {}

        for k, v in step.request.headers.items():
            if baseline.request.headers.get(k) != v:
                diffs[f"header:{k}"] = v

        for k, v in step.request.cookies.items():
            if baseline.request.cookies.get(k) != v:
                diffs[f"cookie:{k}"] = v

        if step.request.body and baseline.request.body:
            if step.request.body != baseline.request.body:
                body_val = step.request.body
                diffs["body"] = (
                    body_val
                    if isinstance(body_val, str)
                    else body_val.decode("utf-8", errors="replace")
                )

        return diffs

    def _detect_candidates(self, diffs: Dict[str, str]) -> List[DynamicToken]:
        """Classifies differences as dynamic token candidates."""
        candidates: List[DynamicToken] = []
        for path, value in diffs.items():
            token_id: str = path.split(":", 1)[-1] if ":" in path else "body_token"

            is_token_name: bool = any(
                x in token_id.lower() for x in ["token", "jwt", "auth", "csrf", "session"]
            )

            if is_token_name:
                location: TokenLocation = self._determine_location(path)
                candidates.append(DynamicToken(
                    token_id=token_id,
                    current_value=str(value),
                    location=location,
                    origin_step=None,  # replaced magic -1 with None
                    status="Unresolved",
                ))
        return candidates

    def _determine_location(self, path: str) -> TokenLocation:
        """Maps a diff path prefix to the appropriate TokenLocation."""
        if path.startswith("header:"):
            return TokenLocation.HEADER
        if path.startswith("cookie:"):
            return TokenLocation.COOKIE
        return TokenLocation.BODY_JSON

    def _generate_curl_template(self, request: StepRequest) -> str:
        """Creates a curl command with {{token}} placeholders."""
        headers_str: str = " ".join(
            [f'-H "{k}: {v}"' for k, v in request.headers.items()]
        )
        return f"curl -X {request.method} '{request.url}' {headers_str}"

    def _extract_static_values(self, step: Step, baseline: Step) -> Dict[str, str]:
        """Extracts values that are identical to the baseline."""
        statics: Dict[str, str] = {}
        for k, v in step.request.headers.items():
            if baseline.request.headers.get(k) == v:
                statics[f"header:{k}"] = v
        return statics
