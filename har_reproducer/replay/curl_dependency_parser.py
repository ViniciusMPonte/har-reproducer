import re
from re import Pattern
from typing import ClassVar, Dict


class CurlDependencyParser:
    DEPENDENCY_PATTERN: ClassVar[Pattern[str]] = re.compile(
        r"^# Token (?P<token_id>[a-z0-9]+) comes from response of step (?P<origin_step>\d+)$",
        re.MULTILINE,
    )

    def parse(self, curl_text: str) -> Dict[str, int]:
        return {
            match.group("token_id"): int(match.group("origin_step"))
            for match in self.DEPENDENCY_PATTERN.finditer(curl_text)
        }
