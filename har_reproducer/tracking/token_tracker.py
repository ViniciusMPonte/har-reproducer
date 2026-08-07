from pathlib import Path
from typing import Dict, List, Optional

from langchain_core.language_models import BaseChatModel

from har_reproducer.agents import AgentFactory
from har_reproducer.models import DynamicToken, Step, StepAnalysis
from har_reproducer.reproduction import CurlGenerator
from har_reproducer.session import SessionStore
from har_reproducer.tracking.baseline_diff import BaselineDiff
from har_reproducer.tracking.candidate_resolver import CandidateResolver
from har_reproducer.tracking.placeholder_applier import PlaceholderApplier


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

        agent_factory: AgentFactory = AgentFactory(llm)
        self.baseline_diff: BaselineDiff = BaselineDiff()
        self.candidate_resolver: CandidateResolver = CandidateResolver(responses_dir, session_store, agent_factory)
        self.placeholder_applier: PlaceholderApplier = PlaceholderApplier(session_store)

    def analyze_step(self, step: Step, baseline_step: Step) -> StepAnalysis:
        diffs: Dict[str, str] = self.baseline_diff.compare(step, baseline_step)
        candidates: List[DynamicToken] = self.baseline_diff.detect_candidates(diffs)
        tokens: List[DynamicToken] = self.candidate_resolver.resolve(candidates, step.index)
        self.placeholder_applier.apply(step.request, tokens)
        template: str = CurlGenerator().generate(step.request, tokens)
        static_values: Dict[str, str] = self.baseline_diff.extract_static_values(step, baseline_step)

        return StepAnalysis(
            step_index=step.index,
            static_values=static_values,
            dynamic_tokens=tokens,
            curl_template=template,
        )
