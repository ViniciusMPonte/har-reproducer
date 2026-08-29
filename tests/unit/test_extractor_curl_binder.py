import shlex

from har_reproducer.replay.curl_token_comment import CurlTokenComment, OriginStatusPhrase, ReplayStatusPhrase
from har_reproducer.reproduction.extractor_curl_binder import ExtractorCurlBinder

TOKEN_ID: str = "ade6a53080262635799eb7ec66e824e8"


def _binder() -> ExtractorCurlBinder:
    return ExtractorCurlBinder(CurlTokenComment(step_index_width=4))


def test_bind_replaces_single_occurrence_and_returns_count_one() -> None:
    curl_text: str = "#!/bin/bash\ncurl -X GET 'https://exemplo.com/login' -H 'X-Plain: SEGREDO123'"

    result, count = _binder().bind(curl_text, TOKEN_ID, 3, "SEGREDO123")

    assert count == 1
    assert f"-H 'X-Plain: {{{{extractor:{TOKEN_ID}}}}}'" in result
    assert "SEGREDO123" not in result


def test_bind_replaces_two_occurrences_in_different_tokens_and_returns_count_two() -> None:
    curl_text: str = (
        "#!/bin/bash\n"
        "curl -X GET 'https://exemplo.com/login' "
        "-H 'X-Plain: SEGREDO123' --cookie 'sess=SEGREDO123'"
    )

    result, count = _binder().bind(curl_text, TOKEN_ID, 3, "SEGREDO123")

    assert count == 2
    assert result.count(f"{{{{extractor:{TOKEN_ID}}}}}") == 2
    assert "SEGREDO123" not in result


def test_bind_returns_count_zero_and_leaves_body_tokens_unchanged_when_literal_not_found() -> None:
    curl_text: str = "#!/bin/bash\ncurl -X GET 'https://exemplo.com/login' -H 'Accept: text/html'"

    result, count = _binder().bind(curl_text, TOKEN_ID, 3, "NAO_EXISTE")

    assert count == 0
    _, original_body = _binder()._split_header_and_body(curl_text)
    _, new_body = _binder()._split_header_and_body(result)
    assert shlex.split(original_body) == shlex.split(new_body)


def test_bind_preserves_shebang_and_unrelated_comment_lines() -> None:
    other_token_id: str = "f04743b512e6241375b3226e7f7c69d3"
    comment: CurlTokenComment = CurlTokenComment(step_index_width=4)
    curl_text: str = "\n".join([
        "#!/bin/bash",
        comment.format_dependency_line(other_token_id, 0),
        "# [Static 1] header:Content-Type←0001",
        "curl -X GET 'https://exemplo.com/login' -H 'X-Plain: SEGREDO123'",
    ])

    result, _ = _binder().bind(curl_text, TOKEN_ID, 3, "SEGREDO123")

    assert result.startswith("#!/bin/bash\n")
    assert comment.format_dependency_line(other_token_id, 0) in result
    assert "# [Static 1] header:Content-Type←0001" in result


def test_bind_over_existing_dependency_line_with_status_suffix_resets_it() -> None:
    comment: CurlTokenComment = CurlTokenComment(step_index_width=4)
    stale_line: str = comment.with_replay_status(
        comment.format_dependency_line(TOKEN_ID, 1, OriginStatusPhrase.UNDETERMINED),
        ReplayStatusPhrase.PROBABLY_STATIC,
    )
    curl_text: str = "\n".join([
        "#!/bin/bash",
        stale_line,
        "curl -X GET 'https://exemplo.com/login' -H 'X-Plain: SEGREDO123'",
    ])

    result, _ = _binder().bind(curl_text, TOKEN_ID, 3, "SEGREDO123")

    fresh_line: str = comment.format_dependency_line(TOKEN_ID, 3)
    assert fresh_line in result
    assert stale_line not in result
    assert "probably static" not in result
    assert "origin location undetermined" not in result


def test_unbind_after_bind_restores_all_occurrences_and_removes_dependency_line() -> None:
    curl_text: str = (
        "#!/bin/bash\n"
        "curl -X GET 'https://exemplo.com/login' "
        "-H 'X-Plain: SEGREDO123' --cookie 'sess=SEGREDO123'"
    )
    bound_text, bind_count = _binder().bind(curl_text, TOKEN_ID, 3, "SEGREDO123")
    assert bind_count == 2

    unbound_text, unbind_count = _binder().unbind(bound_text, TOKEN_ID, "SEGREDO123")

    assert unbind_count == 2
    assert f"{{{{extractor:{TOKEN_ID}}}}}" not in unbound_text
    assert unbound_text.count("SEGREDO123") == 2
    assert CurlTokenComment(step_index_width=4).format_dependency_line(TOKEN_ID, 3) not in unbound_text


def test_unbind_preserves_other_comment_lines() -> None:
    other_token_id: str = "f04743b512e6241375b3226e7f7c69d3"
    comment: CurlTokenComment = CurlTokenComment(step_index_width=4)
    curl_text: str = "\n".join([
        "#!/bin/bash",
        comment.format_dependency_line(other_token_id, 0),
        "curl -X GET 'https://exemplo.com/login' -H 'X-Plain: SEGREDO123'",
    ])
    bound_text, _ = _binder().bind(curl_text, TOKEN_ID, 3, "SEGREDO123")

    unbound_text, _ = _binder().unbind(bound_text, TOKEN_ID, "SEGREDO123")

    assert unbound_text.startswith("#!/bin/bash\n")
    assert comment.format_dependency_line(other_token_id, 0) in unbound_text


def test_bind_then_parse_includes_token_and_unbind_then_parse_excludes_it() -> None:
    comment: CurlTokenComment = CurlTokenComment(step_index_width=4)
    curl_text: str = "#!/bin/bash\ncurl -X GET 'https://exemplo.com/login' -H 'X-Plain: SEGREDO123'"

    bound_text, _ = _binder().bind(curl_text, TOKEN_ID, 3, "SEGREDO123")
    assert comment.parse(bound_text) == {TOKEN_ID: 3}

    unbound_text, _ = _binder().unbind(bound_text, TOKEN_ID, "SEGREDO123")
    assert TOKEN_ID not in comment.parse(unbound_text)
