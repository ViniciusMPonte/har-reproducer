import re
from typing import List

from bs4 import BeautifulSoup

from ..models import (
    StepResponse,
    SuccessCriterion,
    StatusCodeCriterion,
    BodyContainsCriterion,
    UrlMatchCriterion,
    HtmlElementPresentCriterion,
)


class Validator:

    @staticmethod
    def validate(response: StepResponse, criteria: List[SuccessCriterion]) -> bool:

        for criterion in criteria:
            if not Validator._check_criterion(response, criterion):
                return False
        return True

    @staticmethod
    def _check_criterion(response: StepResponse, criterion: SuccessCriterion) -> bool:

        if isinstance(criterion, StatusCodeCriterion):
            return response.status_code == criterion.expected

        elif isinstance(criterion, UrlMatchCriterion):
            url: str = response.redirect_url or ""
            return bool(re.search(criterion.expected, url))

        elif isinstance(criterion, BodyContainsCriterion):
            body: str = response.body if isinstance(response.body, str) else ""
            return criterion.expected in body

        elif isinstance(criterion, HtmlElementPresentCriterion):
            if not response.body or not isinstance(response.body, str):
                return False
            soup: BeautifulSoup = BeautifulSoup(response.body, "html.parser")

            return soup.select_one(criterion.expected) is not None

        return False
