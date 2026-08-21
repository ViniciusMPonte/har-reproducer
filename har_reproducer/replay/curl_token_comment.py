import re
from enum import Enum
from re import Match, Pattern
from typing import ClassVar, Dict, List, Optional, Tuple


class DependencyPhrase(str, Enum):
    COMES_FROM_STEP = "comes from response of step"


class OriginStatusPhrase(str, Enum):
    UNDETERMINED = "origin location undetermined — using literal captured value"
    EXTRACTION_EXHAUSTED = "origin location determined but extraction exhausted — using literal captured value"


class ReplayStatusPhrase(str, Enum):
    PROBABLY_STATIC = "probably static"
    COULD_NOT_EXTRACT = "could not extract value from response, using captured value"


class CurlTokenComment:

    CATEGORY_SEPARATOR: ClassVar[str] = "; "
    CLAUSE_CLOSING_MARKER: ClassVar[str] = "]"

    DEPENDENCY_PATTERN: ClassVar[Pattern[str]] = re.compile(
        r"^# \[Token (?P<token_id>[a-z0-9]+) "
        rf"{re.escape(DependencyPhrase.COMES_FROM_STEP.value)} "
        r"(?P<origin_step>\d+)\]",
        re.MULTILINE,
    )

    UNRESOLVED_PATTERN: ClassVar[Pattern[str]] = re.compile(
        r"^# \[Unresolved (?P<count>\d+)\] (?P<paths>.+)$",
        re.MULTILINE,
    )

    def __init__(self, step_index_width: int) -> None:
        self.step_index_width: int = step_index_width

    def format_dependency_line(
            self, token_id: str, origin_step: int, origin_status: Optional[OriginStatusPhrase] = None
    ) -> str:
        clause: str = (
            f"# [Token {token_id} {DependencyPhrase.COMES_FROM_STEP.value} "
            f"{origin_step:0{self.step_index_width}d}]"
        )
        return self._compose(clause, origin_status, None)

    def format_unresolved_line(self, paths: List[str]) -> str:
        clause: str = f"# [Unresolved {len(paths)}]"
        return f"{clause} {self.CATEGORY_SEPARATOR.join(paths)}"

    def parse_unresolved(self, curl_text: str) -> List[str]:
        match: Optional[Match[str]] = self.UNRESOLVED_PATTERN.search(curl_text)
        if match is None:
            return []
        return match.group("paths").split(self.CATEGORY_SEPARATOR)

    def with_replay_status(self, line: str, phrase: ReplayStatusPhrase) -> str:
        clause, status_text = self._split_clause_and_status(line)
        origin_status: Optional[OriginStatusPhrase]
        origin_status, _ = self._categorize(status_text)
        return self._compose(clause, origin_status, phrase)

    def parse(self, curl_text: str) -> Dict[str, int]:
        return {
            match.group("token_id"): int(match.group("origin_step"))
            for match in self.DEPENDENCY_PATTERN.finditer(curl_text)
        }

    def parse_anchors(self, curl_text: str) -> Dict[str, int]:
        anchors: Dict[str, int] = {}
        for line in curl_text.splitlines():
            match: Optional[Match[str]] = self.DEPENDENCY_PATTERN.match(line)
            if match is None:
                continue
            _, status_text = self._split_clause_and_status(line)
            origin_status, _ = self._categorize(status_text)
            if origin_status is None:
                anchors[match.group("token_id")] = int(match.group("origin_step"))
        return anchors

    def _split_clause_and_status(self, line: str) -> Tuple[str, str]:
        closing_index: int = line.index(self.CLAUSE_CLOSING_MARKER)
        clause: str = line[:closing_index + 1]
        status_text: str = line[closing_index + 1:].strip()
        return clause, status_text

    def _categorize(self, status_text: str) -> Tuple[Optional[OriginStatusPhrase], Optional[ReplayStatusPhrase]]:
        origin_status: Optional[OriginStatusPhrase] = None
        replay_status: Optional[ReplayStatusPhrase] = None
        if not status_text:
            return origin_status, replay_status

        for part in status_text.split(self.CATEGORY_SEPARATOR):
            origin_status = self._match_origin_status(part) or origin_status
            replay_status = self._match_replay_status(part) or replay_status
        return origin_status, replay_status

    @staticmethod
    def _match_origin_status(text: str) -> Optional[OriginStatusPhrase]:
        for member in OriginStatusPhrase:
            if member.value == text:
                return member
        return None

    @staticmethod
    def _match_replay_status(text: str) -> Optional[ReplayStatusPhrase]:
        for member in ReplayStatusPhrase:
            if member.value == text:
                return member
        return None

    def _compose(
            self, clause: str, origin_status: Optional[OriginStatusPhrase], replay_status: Optional[ReplayStatusPhrase]
    ) -> str:
        phrases: List[str] = [status.value for status in (origin_status, replay_status) if status is not None]
        if not phrases:
            return clause
        return f"{clause} {self.CATEGORY_SEPARATOR.join(phrases)}"
