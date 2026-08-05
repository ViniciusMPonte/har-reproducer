from typing import ClassVar, Optional, Set
from urllib.parse import urlparse

from har_reproducer.models import SkipRulesConfig, StepRequest


class StepSkipEvaluator:
    ALLOWED_SCHEMES: ClassVar[Set[str]] = {"http", "https"}

    def __init__(self, skip_rules: SkipRulesConfig) -> None:
        self.skip_rules: SkipRulesConfig = skip_rules

    def skip_reason(self, request: StepRequest) -> Optional[str]:
        scheme: str = urlparse(request.url).scheme.lower()
        if scheme not in self.ALLOWED_SCHEMES:
            return f"unsupported scheme '{scheme}'"
        if request.method in self.skip_rules.methods:
            return f"skippable method '{request.method}'"
        return None
