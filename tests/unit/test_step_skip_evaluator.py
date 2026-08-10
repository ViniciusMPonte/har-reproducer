from typing import Optional

from har_reproducer.models import SkipRulesConfig, StepRequest
from har_reproducer.reproduction.step_skip_evaluator import StepSkipEvaluator


def test_skip_reason_none_for_allowed_scheme_and_method() -> None:
    evaluator: StepSkipEvaluator = StepSkipEvaluator(SkipRulesConfig())

    reason: Optional[str] = evaluator.skip_reason(StepRequest(url="https://x", method="GET"))

    assert reason is None


def test_skip_reason_normalizes_uppercase_scheme() -> None:
    evaluator: StepSkipEvaluator = StepSkipEvaluator(SkipRulesConfig())

    reason: Optional[str] = evaluator.skip_reason(StepRequest(url="HTTPS://x", method="GET"))

    assert reason is None


def test_skip_reason_rejects_unsupported_scheme() -> None:
    evaluator: StepSkipEvaluator = StepSkipEvaluator(SkipRulesConfig())

    reason: Optional[str] = evaluator.skip_reason(StepRequest(url="ftp://x", method="GET"))

    assert reason == "unsupported scheme 'ftp'"


def test_skip_reason_rejects_url_without_scheme() -> None:
    evaluator: StepSkipEvaluator = StepSkipEvaluator(SkipRulesConfig())

    reason: Optional[str] = evaluator.skip_reason(StepRequest(url="/relative/path", method="GET"))

    assert reason == "unsupported scheme ''"


def test_skip_reason_flags_skippable_method() -> None:
    evaluator: StepSkipEvaluator = StepSkipEvaluator(SkipRulesConfig())

    reason: Optional[str] = evaluator.skip_reason(StepRequest(url="https://x", method="OPTIONS"))

    assert reason == "skippable method 'OPTIONS'"
