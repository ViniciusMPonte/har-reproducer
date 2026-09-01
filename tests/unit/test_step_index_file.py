from pathlib import Path
from typing import List

import pytest

from har_reproducer.fs_io.step_index_file import parse_step_index_file


def test_parse_step_index_file_returns_indexes_ignoring_blank_lines(tmp_path: Path) -> None:
    steps_file: Path = tmp_path / "steps.txt"
    steps_file.write_text("0\n3\n\n7\n", encoding="utf-8")

    indexes: List[int] = parse_step_index_file(steps_file)

    assert indexes == [0, 3, 7]


def test_parse_step_index_file_returns_empty_list_for_empty_file(tmp_path: Path) -> None:
    steps_file: Path = tmp_path / "steps.txt"
    steps_file.write_text("", encoding="utf-8")

    indexes: List[int] = parse_step_index_file(steps_file)

    assert indexes == []


def test_parse_step_index_file_returns_empty_list_for_only_blank_lines(tmp_path: Path) -> None:
    steps_file: Path = tmp_path / "steps.txt"
    steps_file.write_text("\n\n  \n", encoding="utf-8")

    indexes: List[int] = parse_step_index_file(steps_file)

    assert indexes == []


def test_parse_step_index_file_raises_file_not_found_for_missing_path(tmp_path: Path) -> None:
    missing_path: Path = tmp_path / "missing.txt"

    with pytest.raises(FileNotFoundError):
        parse_step_index_file(missing_path)


def test_parse_step_index_file_raises_value_error_for_non_numeric_line(tmp_path: Path) -> None:
    steps_file: Path = tmp_path / "steps.txt"
    steps_file.write_text("abc\n", encoding="utf-8")

    with pytest.raises(ValueError):
        parse_step_index_file(steps_file)


def test_parse_step_index_file_preserves_order_and_duplicates(tmp_path: Path) -> None:
    steps_file: Path = tmp_path / "steps.txt"
    steps_file.write_text("3\n3\n1\n", encoding="utf-8")

    indexes: List[int] = parse_step_index_file(steps_file)

    assert indexes == [3, 3, 1]
