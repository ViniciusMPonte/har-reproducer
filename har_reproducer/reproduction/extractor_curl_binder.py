import shlex
from re import Match
from typing import ClassVar, List, Optional, Tuple

from har_reproducer.replay.curl_token_comment import CurlTokenComment


class ExtractorCurlBinder:
    PLACEHOLDER_TEMPLATE: ClassVar[str] = "{{extractor:%s}}"
    HEADER_LINE_PREFIX: ClassVar[str] = "#"
    LINE_CONTINUATION_ARTIFACT: ClassVar[str] = "\n"

    def __init__(self, curl_token_comment: CurlTokenComment) -> None:
        self.curl_token_comment: CurlTokenComment = curl_token_comment

    def bind(self, curl_text: str, token_id: str, origin_step: int, literal_value: str) -> Tuple[str, int]:
        header_lines, body = self._split_header_and_body(curl_text)
        new_body, substitution_count = self._replace_in_body(
            body, literal_value, self._placeholder(token_id)
        )
        dependency_line: str = self.curl_token_comment.format_dependency_line(
            token_id, origin_step, origin_status=None
        )
        new_header_lines: List[str] = self._upsert_dependency_line(header_lines, token_id, dependency_line)
        return self._join(new_header_lines, new_body), substitution_count

    def unbind(self, curl_text: str, token_id: str, replacement_value: str) -> Tuple[str, int]:
        header_lines, body = self._split_header_and_body(curl_text)
        new_body, substitution_count = self._replace_in_body(
            body, self._placeholder(token_id), replacement_value
        )
        new_header_lines: List[str] = self._remove_dependency_line(header_lines, token_id)
        return self._join(new_header_lines, new_body), substitution_count

    def _split_header_and_body(self, curl_text: str) -> Tuple[List[str], str]:
        lines: List[str] = curl_text.splitlines()
        split_index: int = 0
        while split_index < len(lines) and lines[split_index].startswith(self.HEADER_LINE_PREFIX):
            split_index += 1
        header_lines: List[str] = lines[:split_index]
        body: str = "\n".join(lines[split_index:])
        return header_lines, body

    def _replace_in_body(self, body: str, search_value: str, replacement_value: str) -> Tuple[str, int]:
        tokens: List[str] = self._tokenize(body)
        substitution_count: int = 0
        replaced_tokens: List[str] = []
        for token in tokens:
            substitution_count += token.count(search_value)
            replaced_tokens.append(token.replace(search_value, replacement_value))
        return shlex.join(replaced_tokens), substitution_count

    def _tokenize(self, body: str) -> List[str]:
        return [token for token in shlex.split(body) if token != self.LINE_CONTINUATION_ARTIFACT]

    def _placeholder(self, token_id: str) -> str:
        return self.PLACEHOLDER_TEMPLATE % token_id

    def _upsert_dependency_line(
            self, header_lines: List[str], token_id: str, dependency_line: str
    ) -> List[str]:
        existing_index: Optional[int] = self._find_dependency_line_index(header_lines, token_id)
        if existing_index is None:
            return header_lines + [dependency_line]
        updated_lines: List[str] = list(header_lines)
        updated_lines[existing_index] = dependency_line
        return updated_lines

    def _remove_dependency_line(self, header_lines: List[str], token_id: str) -> List[str]:
        existing_index: Optional[int] = self._find_dependency_line_index(header_lines, token_id)
        if existing_index is None:
            return list(header_lines)
        return header_lines[:existing_index] + header_lines[existing_index + 1:]

    def _find_dependency_line_index(self, header_lines: List[str], token_id: str) -> Optional[int]:
        for index, line in enumerate(header_lines):
            match: Optional[Match[str]] = self.curl_token_comment.DEPENDENCY_PATTERN.match(line)
            if match is not None and match.group("token_id") == token_id:
                return index
        return None

    def _join(self, header_lines: List[str], body: str) -> str:
        return "\n".join(header_lines + [body]) + "\n"
