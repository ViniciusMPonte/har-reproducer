from pathlib import Path
from typing import Dict, List, Optional

from langchain_core.language_models import BaseChatModel

from .baseline_diff import BaselineDiff
from .candidate_resolver import CandidateResolver
from .models import DynamicToken, Step, StepAnalysis, StepRequest
from .placeholder_applier import PlaceholderApplier
from .session import SessionStore


class TokenTracker:

    def __init__(
            self,
            responses_dir: Path,
            session_store: SessionStore,
            llm: Optional[BaseChatModel] = None,
    ) -> None:
        self.responses_dir: Path = responses_dir
        self.session_store: SessionStore = session_store
        self.llm: Optional[BaseChatModel] = llm

        self.baseline_diff: BaselineDiff = BaselineDiff()
        self.candidate_resolver: CandidateResolver = CandidateResolver(responses_dir, session_store, llm)
        self.placeholder_applier: PlaceholderApplier = PlaceholderApplier(session_store)

    def analyze_step(self, step: Step, baseline_step: Step) -> StepAnalysis:
        diffs: Dict[str, str] = self.baseline_diff.compare(step, baseline_step)
        candidates: List[DynamicToken] = self.baseline_diff.detect_candidates(diffs)
        tokens: List[DynamicToken] = self.candidate_resolver.resolve(candidates)
        self.placeholder_applier.apply(step.request, tokens)
        template: str = self._generate_curl_template(step.request)
        static_values: Dict[str, str] = self.baseline_diff.extract_static_values(step, baseline_step)

        return StepAnalysis(
            step_index=step.index,
            static_values=static_values,
            dynamic_tokens=tokens,
            curl_template=template,
        )

    @staticmethod
    def _generate_curl_template(request: StepRequest) -> str:
        headers_str: str = " ".join(f'-H "{key}: {value}"' for key, value in request.headers.items())
        return f"curl -X {request.method} '{request.url}' {headers_str}"
