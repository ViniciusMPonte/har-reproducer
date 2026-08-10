from typing import List

from har_reproducer.models import (
    BodyContainsCriterion,
    HtmlElementPresentCriterion,
    StatusCodeCriterion,
    StepResponse,
    SuccessCriterion,
    UrlMatchCriterion,
)
from har_reproducer.validation.validator import Validator


def test_status_code_criterion_matches_and_mismatches() -> None:
    criterion: StatusCodeCriterion = StatusCodeCriterion(type="status_code", expected=200)

    assert Validator.validate(StepResponse(status_code=200), [criterion]) is True
    assert Validator.validate(StepResponse(status_code=404), [criterion]) is False


def test_url_match_criterion_handles_missing_redirect_url() -> None:
    criterion: UrlMatchCriterion = UrlMatchCriterion(type="url_match", expected="dashboard")

    assert Validator.validate(StepResponse(status_code=200, redirect_url="https://x/dashboard"), [criterion]) is True
    assert Validator.validate(StepResponse(status_code=200, redirect_url=None), [criterion]) is False


def test_body_contains_criterion_requires_string_body() -> None:
    criterion: BodyContainsCriterion = BodyContainsCriterion(type="body_contains", expected="ok")

    assert Validator.validate(StepResponse(status_code=200, body="status: ok"), [criterion]) is True
    assert Validator.validate(StepResponse(status_code=200, body=b"status: ok"), [criterion]) is False


def test_html_element_present_criterion() -> None:
    criterion: HtmlElementPresentCriterion = HtmlElementPresentCriterion(
        type="html_element_present", expected="#success"
    )

    assert Validator.validate(
        StepResponse(status_code=200, body="<div id='success'></div>"), [criterion]
    ) is True
    assert Validator.validate(StepResponse(status_code=200, body="<div></div>"), [criterion]) is False


def test_validate_short_circuits_on_first_false_criterion() -> None:
    criteria: List[SuccessCriterion] = [
        StatusCodeCriterion(type="status_code", expected=200),
        StatusCodeCriterion(type="status_code", expected=404),
    ]

    assert Validator.validate(StepResponse(status_code=200), criteria) is False
