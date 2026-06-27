import json
from pathlib import Path
from typing import Dict, List, Any, Optional

from .agents.cookie_agent import CookieAgent
from .agents.css_agent import CSSAgent
from .agents.header_agent import HeaderAgent
from .agents.jsonpath_agent import JSONPathAgent
from .agents.regex_agent import RegexAgent
from .grep_utils import grep_in_real_responses
from .models import Extractor, Step, StepRequest, DynamicToken, TokenLocation, StepAnalysis
from .session import SessionStore


class TokenTracker:
    """
    The Analysis Pipeline: Detects dynamic tokens and determines how to extract them.
    """

    def __init__(self, responses_dir: Path, session_store: SessionStore):
        self.responses_dir = responses_dir
        self.session_store = session_store

    def analyze_step(self, step: Step, baseline_step: Step, is_dry_run: bool = False) -> StepAnalysis:
        """
        Runs the 8-stage pipeline to analyze a step.
        """
        # 1. Baseline Comparison
        diffs = self._compare_to_baseline(step, baseline_step)

        # 2. Dynamic Candidate Detection
        candidates = self._detect_candidates(diffs)

        # 3. Origin Search (Grep)
        resolved_tokens = []
        for candidate in candidates:
            # 4. Extractor Identification / Reuse
            # Check if we already have a verified extractor for this token_id
            if candidate.token_id in self.session_store.state.registry:
                extractor = self.session_store.state.registry[candidate.token_id]
                if extractor.verified:
                    candidate.status = "Resolved"
                    resolved_tokens.append(candidate)
                    continue

            # Try to find origin in real responses
            origin = grep_in_real_responses(self.responses_dir, candidate.current_value)
            if origin:
                candidate.origin_step = origin[0]
                candidate.status = "Resolved"
                resolved_tokens.append(candidate)

                # 5. Extractor Generation
                # In dry-run, we might skip actual LLM generation and just mark as "Potentially Resolved"
                # but for now, we'll try to generate it if we have a sample.
                response_sample = self._load_response(candidate.origin_step)
                if response_sample:
                    if not is_dry_run:
                        extractor = self._generate_extractor(candidate, response_sample)
                        if extractor:
                            self.session_store.state.registry[candidate.token_id] = extractor
                    else:
                        # In dry-run, we just register it as Pending
                        self.session_store.state.registry[candidate.token_id] = Extractor(
                            token_id=candidate.token_id,
                            code="",
                            verified=False,
                            agent_type="Pending"
                        )
            else:
                # Mark as Unresolved if grep fails
                candidate.status = "Unresolved"
                resolved_tokens.append(candidate)

        # 6. Curl Template Generation
        template = self._generate_curl_template(step.request)

        # 7. Validation (Skipped in this basic implementation, assumed by pipeline)

        # 8. StepAnalysis construction
        return StepAnalysis(
            step_index=step.index,
            static_values=self._extract_static_values(step, baseline_step),
            dynamic_tokens=resolved_tokens,
            curl_template=template
        )

    def _load_response(self, step_index: int) -> Optional[dict]:
        """Loads a response JSON file from the responses directory."""
        res_file = self.responses_dir / f"res_{step_index:04d}.json"
        if res_file.exists():
            try:
                return json.loads(res_file.read_text(encoding="utf-8"))
            except Exception as e:
                print(f"[AVISO] Falha ao carregar response do step {step_index}: {e}")
                return None
        return None

    def _generate_extractor(self, candidate: DynamicToken, response_sample: dict) -> Optional[Extractor]:
        """Tries to generate a verified extractor using the appropriate agent."""
        location_map = {
            "Cookie": CookieAgent,
            "Header": HeaderAgent,
            "BodyJSON": JSONPathAgent,
            "BodyHTML": CSSAgent,
            "Script": RegexAgent,
        }
        agent_cls = location_map.get(candidate.location, RegexAgent)

        agent = agent_cls(
            token_id=candidate.token_id,
            response_sample=response_sample,
            expected_value=candidate.current_value
        )
        return agent.run_tdd_loop(origin_step=candidate.origin_step)

    def _compare_to_baseline(self, step: Step, baseline: Step) -> Dict[str, Any]:
        """Detects values that differ from the baseline."""
        diffs = {}

        # Compare headers
        for k, v in step.request.headers.items():
            if baseline.request.headers.get(k) != v:
                diffs[f"header:{k}"] = v

        # Compare cookies
        for k, v in step.request.cookies.items():
            if baseline.request.cookies.get(k) != v:
                diffs[f"cookie:{k}"] = v

        # Compare body (simplified)
        if step.request.body and baseline.request.body:
            if step.request.body != baseline.request.body:
                diffs["body"] = step.request.body

        return diffs

    def _detect_candidates(self, diffs: Dict[str, Any]) -> List[DynamicToken]:
        """Classifies differences as dynamic token candidates."""
        candidates = []
        for path, value in diffs.items():
            token_id = path.split(":", 1)[-1] if ":" in path else "body_token"

            # Heuristic: token-like names
            is_token_name = any(x in token_id.lower() for x in ["token", "jwt", "auth", "csrf", "session"])

            if is_token_name:
                location = self._determine_location(path)
                candidates.append(DynamicToken(
                    token_id=token_id,
                    current_value=str(value),
                    location=location,
                    origin_step=-1,
                    status="Unresolved"
                ))
        return candidates

    def _determine_location(self, path: str) -> TokenLocation:
        if path.startswith("header:"): return "Header"
        if path.startswith("cookie:"): return "Cookie"
        return "BodyJSON"  # Default for this demo

    def _generate_curl_template(self, request: StepRequest) -> str:
        """Creates a curl command with {{token}} placeholders."""
        headers_str = " ".join([f'-H "{k}: {v}"' for k, v in request.headers.items()])
        # Basic replacement of values that are in the session store
        # In a real implementation, this would be more robust.
        return f"curl -X {request.method} '{request.url}' {headers_str}"

    def _extract_static_values(self, step: Step, baseline: Step) -> Dict[str, Any]:
        """Extracts values that are identical to the baseline."""
        statics = {}
        for k, v in step.request.headers.items():
            if baseline.request.headers.get(k) == v:
                statics[f"header:{k}"] = v
        return statics
