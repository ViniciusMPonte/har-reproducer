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
