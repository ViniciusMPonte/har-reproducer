import re
from typing import List

from bs4 import BeautifulSoup

from .models import (
    StepResponse,
    SuccessCriterion,
    StatusCodeCriterion,
    BodyContainsCriterion,
    UrlMatchCriterion,
    HtmlElementPresentCriterion,
    CompositeCriterion,
)


class Validator:
    """
    Validates if a reproduction session has reached the target state
    based on defined SuccessCriteria.
    """

    @staticmethod
    def validate(response: StepResponse, criteria: List[SuccessCriterion]) -> bool:
        """
        Validates the final response against a list of criteria.
        Returns True if ALL criteria are met.
        """
        for criterion in criteria:
            if not Validator._check_criterion(response, criterion):
                return False
        return True

    @staticmethod
    def _check_criterion(response: StepResponse, criterion: SuccessCriterion) -> bool:
        """
        Dispatches criterion checking to the appropriate branch.
        Each branch handles a concrete SuccessCriterion subtype.
        """
        if isinstance(criterion, StatusCodeCriterion):
            return response.status_code == criterion.expected

        elif isinstance(criterion, UrlMatchCriterion):
            # Note: the response model doesn't have the final URL,
            # but in a real scenario, we'd check the redirect_url or the last request URL.
            # For now, we check redirect_url if it exists.
            url: str = response.redirect_url or ""
            return bool(re.search(criterion.expected, url))

        elif isinstance(criterion, BodyContainsCriterion):
            body: str = response.body if isinstance(response.body, str) else ""
            return criterion.expected in body

        elif isinstance(criterion, HtmlElementPresentCriterion):
            if not response.body or not isinstance(response.body, str):
                return False
            soup = BeautifulSoup(response.body, "html.parser")
            # expected is a CSS selector
            return soup.select_one(criterion.expected) is not None

        elif isinstance(criterion, CompositeCriterion):
            return all(Validator._check_criterion(response, c) for c in criterion.expected)

        return False
