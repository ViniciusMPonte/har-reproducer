from typing import Dict, List, NamedTuple, Tuple

from har_reproducer.models import DynamicToken, Step, StepAnalysis, StepRequest, TokenLocation
from har_reproducer.tracking.token_tracker import TokenTracker


class RecordedCompareCall(NamedTuple):
    step: Step
    baseline_step: Step


class FakeBaselineDiff:

    def __init__(self, diffs: Dict[str, str], candidates: List[DynamicToken], static_values: Dict[str, str]) -> None:
        self.diffs: Dict[str, str] = diffs
        self.candidates: List[DynamicToken] = candidates
        self.static_values: Dict[str, str] = static_values
        self.compare_calls: List[RecordedCompareCall] = []
        self.detect_candidates_calls: List[Dict[str, str]] = []

    def compare(self, step: Step, baseline: Step) -> Dict[str, str]:
        self.compare_calls.append(RecordedCompareCall(step, baseline))
        return self.diffs

    def detect_candidates(self, diffs: Dict[str, str]) -> List[DynamicToken]:
        self.detect_candidates_calls.append(diffs)
        return self.candidates

    def extract_static_values(self, step: Step, baseline: Step) -> Dict[str, str]:
        return self.static_values


class FakeCandidateResolver:

    def __init__(self, tokens: List[DynamicToken]) -> None:
        self.tokens: List[DynamicToken] = tokens
        self.resolve_calls: List[Tuple[List[DynamicToken], int]] = []

    def resolve(self, candidates: List[DynamicToken], step_index: int) -> List[DynamicToken]:
        self.resolve_calls.append((candidates, step_index))
        return self.tokens


class FakePlaceholderApplier:

    def __init__(self) -> None:
        self.apply_calls: List[Tuple[StepRequest, List[DynamicToken]]] = []

    def apply(self, request: StepRequest, tokens: List[DynamicToken]) -> None:
        self.apply_calls.append((request, tokens))


class FakeCurlGenerator:

    def __init__(self, template: str) -> None:
        self.template: str = template

    def generate(self, request: StepRequest, tokens: List[DynamicToken]) -> str:
        return self.template


def _step() -> Step:
    return Step(index=0, request=StepRequest(url="https://x", method="GET"))


def _token() -> DynamicToken:
    return DynamicToken(
        token_id="t1", path="header:X", current_value="v", destination_location=TokenLocation.HEADER,
        status="Resolved",
    )


def test_analyze_step_calls_compare_with_step_and_baseline() -> None:
    step: Step = _step()
    baseline: Step = _step()
    baseline_diff: FakeBaselineDiff = FakeBaselineDiff({}, [], {})
    tracker: TokenTracker = TokenTracker(
        baseline_diff, FakeCandidateResolver([]), FakePlaceholderApplier(), FakeCurlGenerator("curl")
    )

    tracker.analyze_step(step, baseline)

    assert baseline_diff.compare_calls == [RecordedCompareCall(step, baseline)]


def test_analyze_step_pipes_detect_candidates_output_into_resolve() -> None:
    step: Step = _step()
    candidates: List[DynamicToken] = [_token()]
    baseline_diff: FakeBaselineDiff = FakeBaselineDiff({"header:X": "v"}, candidates, {})
    candidate_resolver: FakeCandidateResolver = FakeCandidateResolver(candidates)
    tracker: TokenTracker = TokenTracker(
        baseline_diff, candidate_resolver, FakePlaceholderApplier(), FakeCurlGenerator("curl")
    )

    tracker.analyze_step(step, _step())

    assert candidate_resolver.resolve_calls == [(candidates, step.index)]


def test_analyze_step_pipes_resolve_output_into_placeholder_applier_and_analysis() -> None:
    step: Step = _step()
    tokens: List[DynamicToken] = [_token()]
    candidate_resolver: FakeCandidateResolver = FakeCandidateResolver(tokens)
    placeholder_applier: FakePlaceholderApplier = FakePlaceholderApplier()
    tracker: TokenTracker = TokenTracker(
        FakeBaselineDiff({}, [], {}), candidate_resolver, placeholder_applier, FakeCurlGenerator("curl")
    )

    analysis: StepAnalysis = tracker.analyze_step(step, _step())

    assert placeholder_applier.apply_calls == [(step.request, tokens)]
    assert analysis.dynamic_tokens == tokens


def test_analyze_step_curl_template_comes_from_curl_generator() -> None:
    tracker: TokenTracker = TokenTracker(
        FakeBaselineDiff({}, [], {}), FakeCandidateResolver([]), FakePlaceholderApplier(),
        FakeCurlGenerator("curl fixo"),
    )

    analysis: StepAnalysis = tracker.analyze_step(_step(), _step())

    assert analysis.curl_template == "curl fixo"


def test_analyze_step_static_values_come_from_baseline_diff() -> None:
    tracker: TokenTracker = TokenTracker(
        FakeBaselineDiff({}, [], {"header:Same": "1"}), FakeCandidateResolver([]), FakePlaceholderApplier(),
        FakeCurlGenerator("curl"),
    )

    analysis: StepAnalysis = tracker.analyze_step(_step(), _step())

    assert analysis.static_values == {"header:Same": "1"}
