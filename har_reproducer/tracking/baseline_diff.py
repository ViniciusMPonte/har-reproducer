import hashlib
from difflib import SequenceMatcher
from typing import Dict, List, Union

from har_reproducer.models import DynamicToken, Step, TokenLocation


class BaselineDiff:

    def compare(self, step: Step, baseline: Step) -> Dict[str, str]:
        diffs: Dict[str, str] = {}
        diffs.update(self._diff_url(step, baseline))
        diffs.update(self._diff_headers(step, baseline))
        diffs.update(self._diff_cookies(step, baseline))
        diffs.update(self._diff_body(step, baseline))
        return diffs

    @staticmethod
    def _diff_url(step: Step, baseline: Step) -> Dict[str, str]:
        if step.request.url == baseline.request.url:
            return {}
        return {"url": step.request.url}

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

        body_str: str = BaselineDiff._body_as_str(step.request.body)
        baseline_str: str = BaselineDiff._body_as_str(baseline.request.body)

        diffs: Dict[str, str] = {}
        for segment_index, segment in enumerate(BaselineDiff._changed_segments(baseline_str, body_str)):
            path: str = "body" if segment_index == 0 else f"body:{segment_index}"
            diffs[path] = segment
        return diffs

    @staticmethod
    def _body_as_str(body: Union[str, bytes]) -> str:
        if isinstance(body, str):
            return body
        return body.decode("utf-8", errors="replace")

    @staticmethod
    def _changed_segments(baseline: str, current: str) -> List[str]:
        matcher: SequenceMatcher = SequenceMatcher(None, baseline, current, autojunk=False)
        segments: List[str] = []
        for tag, _, _, i2, j2 in matcher.get_opcodes():
            if tag in ("replace", "insert"):
                segments.append(current[i2:j2])
        return segments

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
        if path.startswith("url"):
            return TokenLocation.URL_PARAM
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
