import difflib
import os
import re
import shutil
from pathlib import Path
from typing import ClassVar, Dict, List, Pattern

from tests.support.golden_normalizer import GoldenNormalizer


class GoldenWorkspace:

    DIRECTORY_MARKER: ClassVar[str] = "<EMPTY_DIR>"
    MITM_CAPTURE_DIR_NAME: ClassVar[str] = "mitm_capture"
    UPDATE_GOLDEN_ENV_VAR: ClassVar[str] = "HAR_REPRODUCER_UPDATE_GOLDEN"
    RUN_ID_PATH_PATTERN: ClassVar[Pattern[str]] = re.compile(r"replays/\d{8}_\d{6}")

    def __init__(self, workspace: Path, normalizer: GoldenNormalizer) -> None:
        self.workspace: Path = workspace
        self.normalizer: GoldenNormalizer = normalizer

    def snapshot(self) -> Dict[str, str]:
        return self._capture(self.workspace)

    def assert_matches(self, reference_dir: Path) -> None:
        if self._update_requested():
            self._record(reference_dir)
            return
        actual: Dict[str, str] = self.snapshot()
        expected: Dict[str, str] = self._capture(reference_dir)
        self._assert_equal(actual, expected)

    def _update_requested(self) -> bool:
        return os.environ.get(self.UPDATE_GOLDEN_ENV_VAR) == "1"

    def _record(self, reference_dir: Path) -> None:
        if reference_dir.exists():
            shutil.rmtree(reference_dir)
        reference_dir.mkdir(parents=True)
        for relative, content in self.snapshot().items():
            self._write_reference_entry(reference_dir, relative, content)

    def _write_reference_entry(self, reference_dir: Path, relative: str, content: str) -> None:
        target: Path = reference_dir / relative
        if content == self.DIRECTORY_MARKER:
            target.mkdir(parents=True, exist_ok=True)
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def _capture(self, base: Path) -> Dict[str, str]:
        entries: Dict[str, str] = {}
        for path in self._ordered_paths(base):
            relative: str = self._relative_key(base, path)
            self._add_entry(entries, path, relative)
        return entries

    def _ordered_paths(self, base: Path) -> List[Path]:
        return sorted(base.rglob("*"), key=lambda path: path.relative_to(base).as_posix())

    def _relative_key(self, base: Path, path: Path) -> str:
        relative: str = path.relative_to(base).as_posix()
        return self.RUN_ID_PATH_PATTERN.sub("replays/<RUN_ID>", relative)

    def _add_entry(self, entries: Dict[str, str], path: Path, relative: str) -> None:
        if path.is_dir():
            entries[relative] = self.DIRECTORY_MARKER
            return
        if self._is_under_mitm_capture(relative):
            return
        entries[relative] = self.normalizer.normalize(path.read_text(encoding="utf-8"))

    def _is_under_mitm_capture(self, relative: str) -> bool:
        return self.MITM_CAPTURE_DIR_NAME in relative.split("/")[:-1]

    def _assert_equal(self, actual: Dict[str, str], expected: Dict[str, str]) -> None:
        report: List[str] = self._diff_report(actual, expected)
        if not report:
            return
        raise AssertionError("\n".join(report))

    def _diff_report(self, actual: Dict[str, str], expected: Dict[str, str]) -> List[str]:
        lines: List[str] = []
        lines.extend(self._only_in_lines("Apenas no workspace atual", actual, expected))
        lines.extend(self._only_in_lines("Apenas na referência", expected, actual))
        lines.extend(self._content_diff_lines(actual, expected))
        return lines

    def _only_in_lines(self, label: str, source: Dict[str, str], other: Dict[str, str]) -> List[str]:
        exclusive_keys: List[str] = sorted(set(source) - set(other))
        return [f"{label}: {key}" for key in exclusive_keys]

    def _content_diff_lines(self, actual: Dict[str, str], expected: Dict[str, str]) -> List[str]:
        lines: List[str] = []
        for key in sorted(set(actual) & set(expected)):
            if actual[key] == expected[key]:
                continue
            lines.append(f"Divergência em {key}:")
            lines.extend(self._unified_diff(expected[key], actual[key]))
        return lines

    def _unified_diff(self, expected: str, actual: str) -> List[str]:
        return list(difflib.unified_diff(expected.splitlines(), actual.splitlines(), lineterm=""))
