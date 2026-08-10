from typing import List

from har_reproducer.models import DynamicToken, Step, StepRequest, TokenLocation
from har_reproducer.tracking.baseline_diff import BaselineDiff


def _step(url: str, headers: dict, cookies: dict, body: object, index: int = 0) -> Step:
    return Step(index=index, request=StepRequest(url=url, method="GET", headers=headers, cookies=cookies, body=body))


def test_compare_reports_changed_url() -> None:
    diff: BaselineDiff = BaselineDiff()
    baseline: Step = _step("https://x/a", {}, {}, None)
    step: Step = _step("https://x/b", {}, {}, None)

    result: dict = diff.compare(step, baseline)

    assert result["url"] == "https://x/b"


def test_compare_reports_new_header_and_skips_unchanged_header() -> None:
    diff: BaselineDiff = BaselineDiff()
    baseline: Step = _step("https://x", {"Same": "1"}, {}, None)
    step: Step = _step("https://x", {"Same": "1", "New": "2"}, {}, None)

    result: dict = diff.compare(step, baseline)

    assert result["header:New"] == "2"
    assert "header:Same" not in result


def test_diff_body_ignores_when_either_side_missing() -> None:
    diff: BaselineDiff = BaselineDiff()
    baseline: Step = _step("https://x", {}, {}, None)
    step: Step = _step("https://x", {}, {}, "payload")

    result: dict = diff.compare(step, baseline)

    assert "body" not in result


def test_diff_body_decodes_non_utf8_bytes_with_replace() -> None:
    diff: BaselineDiff = BaselineDiff()
    baseline: Step = _step("https://x", {}, {}, "outro")
    step: Step = _step("https://x", {}, {}, b"\xff\xfe")

    result: dict = diff.compare(step, baseline)

    assert isinstance(result["body"], str)


def test_detect_candidates_builds_dynamic_token_with_cookie_location() -> None:
    diff: BaselineDiff = BaselineDiff()

    candidates: List[DynamicToken] = diff.detect_candidates({"cookie:sid": "abc"})

    assert len(candidates) == 1
    assert candidates[0].destination_location == TokenLocation.COOKIE
    assert candidates[0].status == "UnderReview"
    assert candidates[0].origin_step is None


def test_extract_static_values_returns_only_unchanged_headers() -> None:
    baseline: Step = _step("https://x", {"Same": "1", "Changed": "old"}, {}, None)
    step: Step = _step("https://x", {"Same": "1", "Changed": "new"}, {}, None)

    result: dict = BaselineDiff.extract_static_values(step, baseline)

    assert result == {"header:Same": "1"}
