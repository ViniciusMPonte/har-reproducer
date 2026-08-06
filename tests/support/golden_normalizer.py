import re
from pathlib import Path
from typing import ClassVar, Pattern


class GoldenNormalizer:

    PORT_PATTERN: ClassVar[Pattern[str]] = re.compile(r"127\.0\.0\.1:\d+")
    DATE_JSON_PATTERN: ClassVar[Pattern[str]] = re.compile(r'"Date": "[^"]*"')
    DATE_REPR_PATTERN: ClassVar[Pattern[str]] = re.compile(r"'Date': '[^']*'")
    SERVER_JSON_PATTERN: ClassVar[Pattern[str]] = re.compile(r'"Server": "[^"]*"')
    SERVER_REPR_PATTERN: ClassVar[Pattern[str]] = re.compile(r"'Server': '[^']*'")
    RUN_ID_PATTERN: ClassVar[Pattern[str]] = re.compile(r"replays/\d{8}_\d{6}")

    def __init__(self, workspace: Path, tmp_path: Path) -> None:
        self.workspace: Path = workspace
        self.tmp_path: Path = tmp_path

    def normalize(self, text: str) -> str:
        result: str = text
        result = self._mask_workspace(result)
        result = self._mask_tmp_path(result)
        result = self.PORT_PATTERN.sub("127.0.0.1:<PORT>", result)
        result = self.DATE_JSON_PATTERN.sub('"Date": "<DATE>"', result)
        result = self.DATE_REPR_PATTERN.sub("'Date': '<DATE>'", result)
        result = self.SERVER_JSON_PATTERN.sub('"Server": "<SERVER>"', result)
        result = self.SERVER_REPR_PATTERN.sub("'Server': '<SERVER>'", result)
        result = self.RUN_ID_PATTERN.sub("replays/<RUN_ID>", result)
        return result

    def _mask_workspace(self, text: str) -> str:
        return text.replace(str(self.workspace), "<WORKSPACE>")

    def _mask_tmp_path(self, text: str) -> str:
        return text.replace(str(self.tmp_path), "<TMP>")
