from typing import Optional, Tuple

from har_reproducer.tracking.fragment_matcher import FragmentMatcher


def test_longest_common_finds_the_fragment_after_a_literal_prefix() -> None:
    result: Optional[Tuple[str, int]] = FragmentMatcher.longest_common(
        "Bearer abc123def", '{"token":"abc123def"}'
    )

    assert result == ("abc123def", 7)


def test_longest_common_returns_none_when_coverage_is_below_the_minimum() -> None:
    result: Optional[Tuple[str, int]] = FragmentMatcher.longest_common(
        "http://127.0.0.1:8080", "http:// nada aqui"
    )

    assert result is None


def test_longest_common_accepts_a_fragment_at_the_exact_coverage_boundary() -> None:
    result: Optional[Tuple[str, int]] = FragmentMatcher.longest_common("abcdefgh", "xyzabcdxyz")

    assert result is not None
    fragment, offset = result
    assert fragment == "abcd"
    assert offset == 0
    assert len(fragment) == 4


def test_longest_common_never_returns_the_whole_value() -> None:
    result: Optional[Tuple[str, int]] = FragmentMatcher.longest_common("abcdef", "abcdef")

    assert result is not None
    fragment, _ = result
    assert fragment != "abcdef"


def test_longest_common_returns_none_for_a_single_character_value() -> None:
    result: Optional[Tuple[str, int]] = FragmentMatcher.longest_common("a", "xxxaxxx")

    assert result is None


def test_longest_common_breaks_ties_by_the_smallest_offset() -> None:
    result: Optional[Tuple[str, int]] = FragmentMatcher.longest_common("abcdabcd", "xxxabcdxxx")

    assert result == ("abcd", 0)
