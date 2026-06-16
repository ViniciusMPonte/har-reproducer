import re
from typing import List, Any
from bs4 import BeautifulSoup
from .models import StepResponse, SuccessCriterion

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
        if criterion.type == "status_code":
            return response.status_code == criterion.expected
            
        elif criterion.type == "url_match":
            # Note: the response model doesn't have the final URL, 
            # but in a real scenario, we'd check the redirect_url or the last request URL.
            # For now, we check redirect_url if it exists.
            url = response.redirect_url or ""
            return bool(re.search(str(criterion.expected), url))
            
        elif criterion.type == "body_contains":
            body = response.body if isinstance(response.body, str) else ""
            return str(criterion.expected) in body
            
        elif criterion.type == "html_element_present":
            if not response.body or not isinstance(response.body, str):
                return False
            soup = BeautifulSoup(response.body, "html.parser")
            # expected is a CSS selector
            return soup.select_one(str(criterion.expected)) is not None
            
        elif criterion.type == "composite":
            # Expected is a list of other SuccessCriterion
            sub_criteria = criterion.expected
            if not isinstance(sub_criteria, list):
                return False
            return all(Validator._check_criterion(response, c) for c in sub_criteria)
            
        return False
