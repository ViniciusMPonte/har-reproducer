from typing import Dict, List

from har_reproducer.models import DynamicToken, Step, StepAnalysis
from har_reproducer.reproduction import CurlGenerator
from har_reproducer.tracking.baseline_diff import BaselineDiff
from har_reproducer.tracking.candidate_resolver import CandidateResolver
from har_reproducer.tracking.flow_vocabulary import FlowVocabulary
from har_reproducer.tracking.placeholder_applier import PlaceholderApplier


class TokenTracker:

    def __init__(
            self,
            baseline_diff: BaselineDiff,
            candidate_resolver: CandidateResolver,
            placeholder_applier: PlaceholderApplier,
            curl_generator: CurlGenerator,
            flow_vocabulary: FlowVocabulary,
    ) -> None:
        self.baseline_diff: BaselineDiff = baseline_diff
        self.candidate_resolver: CandidateResolver = candidate_resolver
        self.placeholder_applier: PlaceholderApplier = placeholder_applier
        self.curl_generator: CurlGenerator = curl_generator
        self.flow_vocabulary: FlowVocabulary = flow_vocabulary

    def analyze_step(self, step: Step, baseline_step: Step) -> StepAnalysis:
        self.flow_vocabulary.observe(step.request.url, step.index)
        diffs: Dict[str, str] = self.baseline_diff.compare(step, baseline_step)
        candidates: List[DynamicToken] = self.baseline_diff.detect_candidates(diffs)
        tokens: List[DynamicToken] = self.candidate_resolver.resolve(candidates, step.index)
        self.placeholder_applier.apply(step.request, tokens)
        template: str = self.curl_generator.generate(step.request, tokens)
        static_values: Dict[str, str] = self.baseline_diff.extract_static_values(step, baseline_step)

        return StepAnalysis(
            step_index=step.index,
            static_values=static_values,
            dynamic_tokens=tokens,
            curl_template=template,
        )
