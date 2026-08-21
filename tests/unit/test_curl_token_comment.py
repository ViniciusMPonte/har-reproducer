from har_reproducer.replay.curl_token_comment import (
    CurlTokenComment,
    DependencyPhrase,
    OriginStatusPhrase,
    ReplayStatusPhrase,
)


def test_dependency_phrase_comes_from_step_value() -> None:
    assert DependencyPhrase.COMES_FROM_STEP.value == "comes from response of step"


def test_origin_status_phrase_undetermined_value() -> None:
    assert OriginStatusPhrase.UNDETERMINED.value == "origin location undetermined — using literal captured value"


def test_origin_status_phrase_extraction_exhausted_value() -> None:
    assert OriginStatusPhrase.EXTRACTION_EXHAUSTED.value == (
        "origin location determined but extraction exhausted — using literal captured value"
    )


def test_replay_status_phrase_probably_static_value() -> None:
    assert ReplayStatusPhrase.PROBABLY_STATIC.value == "probably static"


def test_replay_status_phrase_could_not_extract_value() -> None:
    assert ReplayStatusPhrase.COULD_NOT_EXTRACT.value == (
        "could not extract value from response, using captured value"
    )


def test_phrase_enums_are_str_enum() -> None:
    assert isinstance(DependencyPhrase.COMES_FROM_STEP, str)
    assert isinstance(OriginStatusPhrase.UNDETERMINED, str)
    assert isinstance(ReplayStatusPhrase.PROBABLY_STATIC, str)


def test_format_dependency_line_without_status() -> None:
    comment: CurlTokenComment = CurlTokenComment(step_index_width=4)

    line: str = comment.format_dependency_line("abc", 5)

    assert line == "# [Token abc comes from response of step 0005]"


def test_format_dependency_line_with_origin_status() -> None:
    comment: CurlTokenComment = CurlTokenComment(step_index_width=4)

    line: str = comment.format_dependency_line("abc", 5, OriginStatusPhrase.UNDETERMINED)

    assert line.endswith("] origin location undetermined — using literal captured value")


def test_with_replay_status_appends_status_to_line_without_status() -> None:
    comment: CurlTokenComment = CurlTokenComment(step_index_width=4)
    line: str = comment.format_dependency_line("abc", 5)

    updated: str = comment.with_replay_status(line, ReplayStatusPhrase.PROBABLY_STATIC)

    assert updated.endswith("] probably static")


def test_with_replay_status_preserves_origin_status_and_concatenates_in_order() -> None:
    comment: CurlTokenComment = CurlTokenComment(step_index_width=4)
    line: str = comment.format_dependency_line("abc", 5, OriginStatusPhrase.UNDETERMINED)

    updated: str = comment.with_replay_status(line, ReplayStatusPhrase.PROBABLY_STATIC)

    assert updated.endswith(
        "] origin location undetermined — using literal captured value; probably static"
    )


def test_with_replay_status_replaces_previous_replay_status_instead_of_accumulating() -> None:
    comment: CurlTokenComment = CurlTokenComment(step_index_width=4)
    line: str = comment.format_dependency_line("abc", 5)

    once: str = comment.with_replay_status(line, ReplayStatusPhrase.PROBABLY_STATIC)
    twice: str = comment.with_replay_status(once, ReplayStatusPhrase.COULD_NOT_EXTRACT)

    assert twice.endswith("] could not extract value from response, using captured value")
    assert "probably static" not in twice


def test_parse_extracts_dependency_line_without_status() -> None:
    comment: CurlTokenComment = CurlTokenComment(step_index_width=4)
    text: str = comment.format_dependency_line("abc", 5) + "\ncurl -X GET https://x"

    result: dict = comment.parse(text)

    assert result == {"abc": 5}


def test_parse_extracts_dependency_line_with_any_status_attached() -> None:
    comment: CurlTokenComment = CurlTokenComment(step_index_width=4)
    line: str = comment.format_dependency_line("abc", 5, OriginStatusPhrase.EXTRACTION_EXHAUSTED)
    annotated: str = comment.with_replay_status(line, ReplayStatusPhrase.COULD_NOT_EXTRACT)
    text: str = annotated + "\ncurl -X GET https://x"

    result: dict = comment.parse(text)

    assert result == {"abc": 5}


def test_parse_ignores_arbitrary_unrelated_comment_line() -> None:
    comment: CurlTokenComment = CurlTokenComment(step_index_width=4)
    text: str = (
        comment.format_dependency_line("abc", 1)
        + "\n# nota qualquer sobre este step\n"
        + "curl -X GET https://x"
    )

    result: dict = comment.parse(text)

    assert result == {"abc": 1}


def test_parse_extracts_multiple_dependencies() -> None:
    comment: CurlTokenComment = CurlTokenComment(step_index_width=4)
    text: str = (
        comment.format_dependency_line("abc", 1)
        + "\n"
        + comment.format_dependency_line("def", 3)
        + "\ncurl -X GET https://x"
    )

    result: dict = comment.parse(text)

    assert result == {"abc": 1, "def": 3}


def test_parse_returns_empty_dict_without_comments() -> None:
    comment: CurlTokenComment = CurlTokenComment(step_index_width=4)

    result: dict = comment.parse("curl -X GET https://x")

    assert result == {}


def test_format_unresolved_line_joins_paths_with_the_category_separator() -> None:
    comment: CurlTokenComment = CurlTokenComment(step_index_width=4)

    line: str = comment.format_unresolved_line(["header:Accept", "url"])

    assert line == "# [Unresolved 2] header:Accept; url"


def test_parse_unresolved_round_trips_the_formatted_line() -> None:
    comment: CurlTokenComment = CurlTokenComment(step_index_width=4)

    assert comment.parse_unresolved(comment.format_unresolved_line(["a", "b"])) == ["a", "b"]


def test_parse_unresolved_returns_empty_list_for_empty_text() -> None:
    comment: CurlTokenComment = CurlTokenComment(step_index_width=4)

    assert comment.parse_unresolved("") == []


def test_parse_unresolved_returns_empty_list_for_curl_without_the_clause() -> None:
    comment: CurlTokenComment = CurlTokenComment(step_index_width=4)

    assert comment.parse_unresolved("#!/bin/bash\ncurl -X GET x") == []


def test_dependency_pattern_does_not_match_the_unresolved_line() -> None:
    comment: CurlTokenComment = CurlTokenComment(step_index_width=4)

    assert CurlTokenComment.DEPENDENCY_PATTERN.findall(comment.format_unresolved_line(["a"])) == []


def test_parse_unresolved_does_not_match_the_dependency_line() -> None:
    comment: CurlTokenComment = CurlTokenComment(step_index_width=4)

    assert comment.parse_unresolved(comment.format_dependency_line("abc123", 7)) == []


def test_parse_still_finds_the_dependency_when_both_lines_are_present() -> None:
    comment: CurlTokenComment = CurlTokenComment(step_index_width=4)
    curl_text: str = "\n".join([
        comment.format_dependency_line("abc123", 7),
        comment.format_unresolved_line(["header:Accept", "url"]),
        "curl -X GET x",
    ])

    assert comment.parse(curl_text) == {"abc123": 7}
    assert comment.parse_unresolved(curl_text) == ["header:Accept", "url"]


def test_parse_unresolved_returns_the_first_occurrence_only() -> None:
    comment: CurlTokenComment = CurlTokenComment(step_index_width=4)
    curl_text: str = "\n".join([
        comment.format_unresolved_line(["primeiro"]),
        comment.format_unresolved_line(["segundo"]),
    ])

    assert comment.parse_unresolved(curl_text) == ["primeiro"]


def test_parse_anchors_includes_dependency_without_status() -> None:
    comment: CurlTokenComment = CurlTokenComment(step_index_width=4)
    text: str = comment.format_dependency_line("abc", 2) + "\ncurl -X GET https://x"

    assert comment.parse_anchors(text) == {"abc": 2}


def test_parse_anchors_excludes_dependency_with_origin_status_undetermined() -> None:
    comment: CurlTokenComment = CurlTokenComment(step_index_width=4)
    text: str = (
        comment.format_dependency_line("abc", 2, OriginStatusPhrase.UNDETERMINED)
        + "\ncurl -X GET https://x"
    )

    assert comment.parse_anchors(text) == {}


def test_parse_anchors_excludes_dependency_with_origin_status_extraction_exhausted() -> None:
    comment: CurlTokenComment = CurlTokenComment(step_index_width=4)
    text: str = (
        comment.format_dependency_line("abc", 2, OriginStatusPhrase.EXTRACTION_EXHAUSTED)
        + "\ncurl -X GET https://x"
    )

    assert comment.parse_anchors(text) == {}


def test_parse_anchors_includes_dependency_with_only_replay_status() -> None:
    comment: CurlTokenComment = CurlTokenComment(step_index_width=4)
    line: str = comment.format_dependency_line("abc", 2)
    annotated: str = comment.with_replay_status(line, ReplayStatusPhrase.PROBABLY_STATIC)

    assert comment.parse_anchors(annotated + "\ncurl -X GET https://x") == {"abc": 2}


def test_parse_anchors_excludes_dependency_with_both_origin_and_replay_status() -> None:
    comment: CurlTokenComment = CurlTokenComment(step_index_width=4)
    line: str = comment.format_dependency_line("abc", 2, OriginStatusPhrase.UNDETERMINED)
    annotated: str = comment.with_replay_status(line, ReplayStatusPhrase.PROBABLY_STATIC)

    assert comment.parse_anchors(annotated + "\ncurl -X GET https://x") == {}


def test_parse_anchors_mixes_frozen_and_recalculable_dependencies_regardless_of_order() -> None:
    comment: CurlTokenComment = CurlTokenComment(step_index_width=4)
    text: str = "\n".join([
        comment.format_dependency_line("frozen", 1, OriginStatusPhrase.UNDETERMINED),
        comment.format_dependency_line("recalculable", 3),
        "curl -X GET https://x",
    ])

    assert comment.parse_anchors(text) == {"recalculable": 3}


def test_parse_anchors_returns_empty_dict_without_any_dependency_line() -> None:
    comment: CurlTokenComment = CurlTokenComment(step_index_width=4)

    assert comment.parse_anchors("curl -X GET https://x") == {}


def test_parse_still_returns_every_dependency_regardless_of_status() -> None:
    comment: CurlTokenComment = CurlTokenComment(step_index_width=4)
    text: str = "\n".join([
        comment.format_dependency_line("frozen", 1, OriginStatusPhrase.UNDETERMINED),
        comment.format_dependency_line("recalculable", 3),
        "curl -X GET https://x",
    ])

    assert comment.parse(text) == {"frozen": 1, "recalculable": 3}
