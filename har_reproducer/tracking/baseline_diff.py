import hashlib
from typing import Dict, List, Union

from har_reproducer.models import DynamicToken, Step, TokenLocation


class BaselineDiff:

    def compare(self, step: Step, baseline: Step) -> Dict[str, str]:
        diffs: Dict[str, str] = {}
        diffs.update(self._diff_headers(step, baseline))
        diffs.update(self._diff_cookies(step, baseline))
        diffs.update(self._diff_body(step, baseline))
        return diffs

    @staticmethod
    def _diff_headers(step: Step, baseline: Step) -> Dict[str, str]:
        return {
            f"header:{key}": value
            for key, value in step.request.headers.items()
            if baseline.request.headers.get(key) != value
        }

    @staticmethod
    def _diff_cookies(step: Step, baseline: Step) -> Dict[str, str]:
        return {
            f"cookie:{key}": value
            for key, value in step.request.cookies.items()
            if baseline.request.cookies.get(key) != value
        }

    @staticmethod
    def _diff_body(step: Step, baseline: Step) -> Dict[str, str]:
        if not step.request.body or not baseline.request.body:
            return {}
        if step.request.body == baseline.request.body:
            return {}

        body_value: Union[str, bytes] = step.request.body
        body_str: str = (
            body_value if isinstance(body_value, str) else body_value.decode("utf-8", errors="replace")
        )
        return {"body": body_str}

    def detect_candidates(self, diffs: Dict[str, str]) -> List[DynamicToken]:
        return [self._build_candidate(path, value) for path, value in diffs.items()]

    def _build_candidate(self, path: str, value: str) -> DynamicToken:
        location: TokenLocation = self._determine_location(path)
        provisional_id: str = hashlib.md5(path.encode("utf-8")).hexdigest()

        return DynamicToken(
            token_id=provisional_id,
            path=path,
            current_value=value,
            destination_location=location,
            origin_step=None,
            status="UnderReview",
        )

    @staticmethod
    def _determine_location(path: str) -> TokenLocation:
        if path.startswith("header:"):
            return TokenLocation.HEADER
        if path.startswith("cookie:"):
            return TokenLocation.COOKIE
        return TokenLocation.BODY_JSON

    @staticmethod
    def extract_static_values(step: Step, baseline: Step) -> Dict[str, str]:
        return {
            f"header:{key}": value
            for key, value in step.request.headers.items()
            if baseline.request.headers.get(key) == value
        }
