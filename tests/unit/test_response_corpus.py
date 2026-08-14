import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from har_reproducer.tracking.response_corpus import ResponseCorpus


class ResponseCorpusFixture:
    STEP_INDEX_WIDTH: int = 4


@pytest.fixture
def responses_dir(tmp_path: Path) -> Path:
    directory: Path = tmp_path / "real_responses"
    directory.mkdir()
    return directory


def _write_response(directory: Path, index: int, payload: Dict[str, Any]) -> Path:
    path: Path = directory / f"res_{index:0{ResponseCorpusFixture.STEP_INDEX_WIDTH}d}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _corpus(directory: Path) -> ResponseCorpus:
    return ResponseCorpus(directory, ResponseCorpusFixture.STEP_INDEX_WIDTH)


def test_eligible_indexes_keeps_only_strictly_earlier_steps(responses_dir: Path) -> None:
    for index in range(6):
        _write_response(responses_dir, index, {"status_code": 200})

    assert _corpus(responses_dir).eligible_indexes(3) == [0, 1, 2]


def test_eligible_indexes_of_first_step_is_empty(responses_dir: Path) -> None:
    _write_response(responses_dir, 0, {"status_code": 200})

    assert _corpus(responses_dir).eligible_indexes(0) == []


def test_eligible_indexes_ignores_file_out_of_pattern(responses_dir: Path) -> None:
    _write_response(responses_dir, 1, {"status_code": 200})
    (responses_dir / "res_semnumero.json").write_text("{}", encoding="utf-8")

    assert _corpus(responses_dir).eligible_indexes(9) == [1]


def test_searchable_text_keeps_header_quotes_raw(responses_dir: Path) -> None:
    _write_response(responses_dir, 1, {"headers": {"ETag": 'W/"9b1-19a1d941a25"'}})

    text: Optional[str] = _corpus(responses_dir).searchable_text(1)

    assert text is not None
    assert 'W/"9b1-19a1d941a25"' in text


def test_searchable_text_keeps_body_json_unescaped(responses_dir: Path) -> None:
    _write_response(responses_dir, 1, {"body": '{"token":"abc"}'})

    text: Optional[str] = _corpus(responses_dir).searchable_text(1)

    assert text is not None
    assert '{"token":"abc"}' in text
    assert "\\" not in text


def test_searchable_text_serializes_every_field_in_fixed_order(responses_dir: Path) -> None:
    _write_response(responses_dir, 1, {
        "headers": {"ETag": "abc"},
        "cookies": {"sid": "xyz"},
        "redirect_url": "https://example.com/next",
        "body": "corpo",
    })

    assert _corpus(responses_dir).searchable_text(1) == "ETag: abc\nsid=xyz\nhttps://example.com/next\ncorpo"


def test_searchable_text_of_empty_response_is_empty_string(responses_dir: Path) -> None:
    _write_response(responses_dir, 1, {})

    assert _corpus(responses_dir).searchable_text(1) == ""


def test_searchable_text_of_missing_response_is_none(responses_dir: Path) -> None:
    assert _corpus(responses_dir).searchable_text(1) is None


def test_response_of_missing_file_is_none_without_warning(
        responses_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _corpus(responses_dir).response(7) is None
    assert capsys.readouterr().out == ""


def test_response_of_corrupted_json_is_none_with_warning(
        responses_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (responses_dir / "res_0007.json").write_text("{nao eh json", encoding="utf-8")

    assert _corpus(responses_dir).response(7) is None
    assert "[AVISO]" in capsys.readouterr().out


def test_searchable_text_is_memoized_per_step(responses_dir: Path) -> None:
    path: Path = _write_response(responses_dir, 1, {"body": "conteudo"})
    corpus: ResponseCorpus = _corpus(responses_dir)

    first: Optional[str] = corpus.searchable_text(1)
    path.unlink()

    assert corpus.searchable_text(1) == first == "conteudo"


def test_missing_response_is_not_memoized(responses_dir: Path) -> None:
    corpus: ResponseCorpus = _corpus(responses_dir)

    assert corpus.response(9) is None

    _write_response(responses_dir, 9, {"body": "chegou depois"})

    response: Optional[Dict[str, Any]] = corpus.response(9)
    assert response is not None
    assert response["body"] == "chegou depois"


def test_eligible_indexes_is_never_memoized(responses_dir: Path) -> None:
    _write_response(responses_dir, 0, {"status_code": 200})
    corpus: ResponseCorpus = _corpus(responses_dir)

    assert corpus.eligible_indexes(9) == [0]

    _write_response(responses_dir, 1, {"status_code": 200})

    assert corpus.eligible_indexes(9) == [0, 1]


def test_response_returns_raw_dict(responses_dir: Path) -> None:
    _write_response(responses_dir, 2, {"status_code": 304, "body_mime": "text/html", "skipped": False})

    response: Optional[Dict[str, Any]] = _corpus(responses_dir).response(2)

    assert response == {"status_code": 304, "body_mime": "text/html", "skipped": False}


def test_searchable_text_decodes_bytes_body(responses_dir: Path) -> None:
    _write_response(responses_dir, 1, {"body": "corpo com acento é"})

    text: Optional[str] = _corpus(responses_dir).searchable_text(1)

    assert text == "corpo com acento é"


def test_extract_step_index_parses_valid_filename() -> None:
    assert ResponseCorpus._extract_step_index("res_0007.json") == 7


def test_extract_step_index_returns_none_for_invalid_filename() -> None:
    result: Optional[int] = ResponseCorpus._extract_step_index("nomeinvalido.json")

    assert result is None


def test_searchable_text_skips_falsy_optional_fields(responses_dir: Path) -> None:
    _write_response(responses_dir, 1, {"headers": {}, "cookies": None, "redirect_url": None, "body": ""})

    assert _corpus(responses_dir).searchable_text(1) == ""


def test_eligible_indexes_returns_ascending_order(responses_dir: Path) -> None:
    for index in [5, 0, 3, 1]:
        _write_response(responses_dir, index, {"status_code": 200})

    indexes: List[int] = _corpus(responses_dir).eligible_indexes(9)

    assert indexes == [0, 1, 3, 5]
