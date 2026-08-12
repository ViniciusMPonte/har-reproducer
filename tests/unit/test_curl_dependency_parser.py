from har_reproducer.replay.curl_dependency_parser import CurlDependencyParser
from har_reproducer.replay.replay_runner import ReplayRunner


def test_parse_extracts_single_dependency() -> None:
    parser: CurlDependencyParser = CurlDependencyParser()

    result: dict = parser.parse("# Token abc123 comes from response of step 4\ncurl -X GET https://x")

    assert result == {"abc123": 4}


def test_parse_returns_empty_dict_without_comments() -> None:
    parser: CurlDependencyParser = CurlDependencyParser()

    result: dict = parser.parse("curl -X GET https://x")

    assert result == {}


def test_parse_extracts_multiple_dependencies() -> None:
    parser: CurlDependencyParser = CurlDependencyParser()
    text: str = (
        "# Token abc comes from response of step 1\n"
        "# Token def comes from response of step 3\n"
        "curl -X GET https://x"
    )

    result: dict = parser.parse(text)

    assert result == {"abc": 1, "def": 3}


def test_parse_still_extracts_dependency_annotated_as_probably_static() -> None:
    parser: CurlDependencyParser = CurlDependencyParser()
    text: str = (
        f"# Token abc comes from response of step 2{ReplayRunner.STATIC_WARNING_SUFFIX}\n"
        "curl -X GET https://x"
    )

    result: dict = parser.parse(text)

    assert result == {"abc": 2}


def test_parse_ignores_exhausted_annotation_line() -> None:
    parser: CurlDependencyParser = CurlDependencyParser()
    text: str = (
        "# Token abc comes from response of step 1\n"
        "# Token abc origin location determined but extraction exhausted — "
        "using literal captured value\n"
        "curl -X GET https://x"
    )

    result: dict = parser.parse(text)

    assert result == {"abc": 1}
