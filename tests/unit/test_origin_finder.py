import base64
import json
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

from har_reproducer.models import OriginContainer, OriginMatch
from har_reproducer.tracking.origin_finder import OriginFinder
from har_reproducer.tracking.response_corpus import ResponseCorpus


class OriginFinderFixture:
    STEP_INDEX_WIDTH: int = 4


@pytest.fixture
def responses_dir(tmp_path: Path) -> Path:
    directory: Path = tmp_path / "real_responses"
    directory.mkdir()
    return directory


def _write_response(directory: Path, index: int, payload: Dict[str, Any]) -> None:
    path: Path = directory / f"res_{index:0{OriginFinderFixture.STEP_INDEX_WIDTH}d}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")


def _finder(directory: Path) -> OriginFinder:
    return OriginFinder(ResponseCorpus(directory, OriginFinderFixture.STEP_INDEX_WIDTH))


def test_find_returns_header_key_of_exact_match(responses_dir: Path) -> None:
    _write_response(responses_dir, 1, {"headers": {"ETag": 'W/"9b1-abc"'}})

    match: Optional[OriginMatch] = _finder(responses_dir).find('W/"9b1-abc"', 0, 5)

    assert match == OriginMatch(step_index=1, origin_key="ETag", origin_container=OriginContainer.HEADER)


def test_find_respects_temporal_causality(responses_dir: Path) -> None:
    _write_response(responses_dir, 1, {"headers": {"ETag": 'W/"9b1-abc"'}})

    assert _finder(responses_dir).find('W/"9b1-abc"', 0, 1) is None


def test_find_ignores_steps_below_the_lower_window(responses_dir: Path) -> None:
    _write_response(responses_dir, 1, {"headers": {"ETag": "valor"}})

    assert _finder(responses_dir).find("valor", 3, 10) is None


def test_find_keeps_step_at_the_lower_window_bound(responses_dir: Path) -> None:
    _write_response(responses_dir, 3, {"headers": {"ETag": "valor"}})

    match: Optional[OriginMatch] = _finder(responses_dir).find("valor", 3, 10)

    assert match is not None
    assert match.step_index == 3


def test_find_wins_by_lowest_step_index(responses_dir: Path) -> None:
    _write_response(responses_dir, 2, {"body": "contem valor aqui"})
    _write_response(responses_dir, 4, {"body": "contem valor aqui"})

    match: Optional[OriginMatch] = _finder(responses_dir).find("valor", 0, 10)

    assert match is not None
    assert match.step_index == 2


def test_raw_variant_wins_over_step_order(responses_dir: Path) -> None:
    encoded: str = base64.b64encode(b"segredo").decode("ascii")
    _write_response(responses_dir, 2, {"body": f"payload {encoded} fim"})
    _write_response(responses_dir, 4, {"body": "payload segredo fim"})

    match: Optional[OriginMatch] = _finder(responses_dir).find("segredo", 0, 10)

    assert match is not None
    assert match.step_index == 4


def test_cookie_wins_over_header_in_the_same_response(responses_dir: Path) -> None:
    _write_response(responses_dir, 1, {
        "headers": {"X-Token": "abc123"},
        "cookies": {"session": "abc123"},
    })

    match: Optional[OriginMatch] = _finder(responses_dir).find("abc123", 0, 5)

    assert match is not None
    assert match.origin_container is OriginContainer.COOKIE
    assert match.origin_key == "session"


def test_match_only_in_body_has_no_origin_key(responses_dir: Path) -> None:
    _write_response(responses_dir, 1, {"body": '{"token":"abc123"}'})

    match: Optional[OriginMatch] = _finder(responses_dir).find("abc123", 0, 5)

    assert match is not None
    assert match.step_index == 1
    assert match.origin_key is None
    assert match.origin_container is None


def test_match_in_redirect_url_has_no_origin_key(responses_dir: Path) -> None:
    _write_response(responses_dir, 1, {"redirect_url": "https://example.com/?t=abc123"})

    match: Optional[OriginMatch] = _finder(responses_dir).find("abc123", 0, 5)

    assert match is not None
    assert match.origin_key is None
    assert match.origin_container is None


def test_substring_of_header_value_matches_without_origin_key(responses_dir: Path) -> None:
    _write_response(responses_dir, 1, {"headers": {"Cross-Origin-Opener-Policy": "same-origin-allow-popups"}})

    match: Optional[OriginMatch] = _finder(responses_dir).find("same-origin", 0, 5)

    assert match is not None
    assert match.step_index == 1
    assert match.origin_key is None
    assert match.origin_container is None


def test_base64_variant_match_in_header_has_no_origin_key(responses_dir: Path) -> None:
    encoded: str = base64.b64encode(b"segredo").decode("ascii")
    _write_response(responses_dir, 1, {"headers": {"X-Token": encoded}})

    match: Optional[OriginMatch] = _finder(responses_dir).find("segredo", 0, 5)

    assert match is not None
    assert match.step_index == 1
    assert match.origin_key is None
    assert match.origin_container is None


def test_multiline_value_requires_integral_match(responses_dir: Path) -> None:
    _write_response(responses_dir, 1, {"body": "BBB"})

    assert _finder(responses_dir).find("AAA\nBBB", 0, 5) is None


def test_multiline_value_matches_when_integral(responses_dir: Path) -> None:
    _write_response(responses_dir, 1, {"body": "prefixo AAA\nBBB sufixo"})

    match: Optional[OriginMatch] = _finder(responses_dir).find("AAA\nBBB", 0, 5)

    assert match is not None
    assert match.step_index == 1


def test_find_returns_none_without_eligible_steps(responses_dir: Path) -> None:
    assert _finder(responses_dir).find("valor", 0, 5) is None


def test_find_skips_unreadable_response(responses_dir: Path) -> None:
    (responses_dir / "res_0001.json").write_text("{nao eh json", encoding="utf-8")
    _write_response(responses_dir, 2, {"headers": {"ETag": "valor"}})

    match: Optional[OriginMatch] = _finder(responses_dir).find("valor", 0, 5)

    assert match is not None
    assert match.step_index == 2


def test_cookie_exact_match_yields_cookie_container(responses_dir: Path) -> None:
    _write_response(responses_dir, 1, {"cookies": {"session": "abc123"}})

    match: Optional[OriginMatch] = _finder(responses_dir).find("abc123", 0, 5)

    assert match is not None
    assert match.origin_container is OriginContainer.COOKIE
    assert match.origin_key == "session"
