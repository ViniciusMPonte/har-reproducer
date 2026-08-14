from typing import List, Optional

from har_reproducer.models import DynamicToken, StepRequest, TokenLocation
from har_reproducer.replay.curl_token_comment import CurlTokenComment
from har_reproducer.reproduction.curl_generator import CurlGenerator


def _token(
        origin_step: Optional[int], origin_location: Optional[TokenLocation], extraction_exhausted: bool = False
) -> DynamicToken:
    return DynamicToken(
        token_id="abc",
        path="header:X",
        current_value="v",
        destination_location=TokenLocation.HEADER,
        origin_step=origin_step,
        origin_location=origin_location,
        extraction_exhausted=extraction_exhausted,
        status="Resolved",
    )


def _generator() -> CurlGenerator:
    return CurlGenerator(CurlTokenComment(step_index_width=4))


def test_generate_without_commentable_tokens_reports_them_as_unresolved() -> None:
    generator: CurlGenerator = _generator()
    request: StepRequest = StepRequest(url="https://x", method="GET")

    lines: List[str] = generator.generate(request, [_token(None, None)]).splitlines()

    assert lines[0] == "# [Unresolved 1] header:X"
    assert lines[1].startswith("curl -X GET")


def test_generate_adds_undetermined_location_comment() -> None:
    generator: CurlGenerator = _generator()
    request: StepRequest = StepRequest(url="https://x", method="GET")

    output: str = generator.generate(request, [_token(2, None)])

    assert "# [Token abc comes from response of step 0002]" in output
    assert "origin location undetermined" in output


def test_generate_adds_extraction_exhausted_comment() -> None:
    generator: CurlGenerator = _generator()
    request: StepRequest = StepRequest(url="https://x", method="GET")

    output: str = generator.generate(request, [_token(2, TokenLocation.COOKIE, extraction_exhausted=True)])

    assert "# [Token abc comes from response of step 0002]" in output
    assert "extraction exhausted" in output


def test_generate_omits_cookie_flag_when_no_cookies() -> None:
    generator: CurlGenerator = _generator()
    request: StepRequest = StepRequest(url="https://x", method="GET")

    output: str = generator.generate(request, [])

    assert "--cookie" not in output


def test_generate_includes_body_flag_with_payload() -> None:
    generator: CurlGenerator = _generator()
    request: StepRequest = StepRequest(url="https://x", method="POST", body="payload")

    output: str = generator.generate(request, [])

    assert "--data-binary" in output
    assert "payload" in output


def _token_with_path(origin_step: Optional[int], path: str) -> DynamicToken:
    return DynamicToken(
        token_id="abc",
        path=path,
        current_value="v",
        destination_location=TokenLocation.HEADER,
        origin_step=origin_step,
        origin_location=TokenLocation.HEADER,
        status="NotFound" if origin_step is None else "Resolved",
    )


def test_generate_appends_unresolved_line_after_the_dependency_lines() -> None:
    generator: CurlGenerator = _generator()
    request: StepRequest = StepRequest(url="https://x", method="GET")
    tokens: List[DynamicToken] = [
        _token_with_path(3, "header:X-Csrf"),
        _token_with_path(None, "header:Accept"),
        _token_with_path(None, "url"),
    ]

    lines: List[str] = generator.generate(request, tokens).splitlines()

    assert lines[0] == "# [Token abc comes from response of step 0003]"
    assert lines[1] == "# [Unresolved 2] header:Accept; url"
    assert lines[2].startswith("curl -X GET")


def test_generate_without_unresolved_tokens_keeps_only_dependency_lines() -> None:
    generator: CurlGenerator = _generator()
    request: StepRequest = StepRequest(url="https://x", method="GET")

    output: str = generator.generate(request, [_token_with_path(3, "header:X-Csrf")])

    assert "Unresolved" not in output
    assert "# [Token abc comes from response of step 0003]" in output


def test_generate_with_only_unresolved_tokens_emits_a_single_comment_line() -> None:
    generator: CurlGenerator = _generator()
    request: StepRequest = StepRequest(url="https://x", method="GET")
    tokens: List[DynamicToken] = [_token_with_path(None, "header:Accept"), _token_with_path(None, "url")]

    lines: List[str] = generator.generate(request, tokens).splitlines()

    assert lines[0] == "# [Unresolved 2] header:Accept; url"
    assert lines[1].startswith("curl -X GET")


def test_generate_with_empty_token_list_has_no_comment() -> None:
    generator: CurlGenerator = _generator()
    request: StepRequest = StepRequest(url="https://x", method="GET")

    output: str = generator.generate(request, [])

    assert output.startswith("curl -X GET")
    assert "#" not in output


def test_unresolved_line_keeps_the_order_of_the_received_tokens() -> None:
    generator: CurlGenerator = _generator()
    request: StepRequest = StepRequest(url="https://x", method="GET")
    tokens: List[DynamicToken] = [
        _token_with_path(None, "url"),
        _token_with_path(None, "header:Accept"),
        _token_with_path(None, "cookie:sid"),
    ]

    output: str = generator.generate(request, tokens)

    assert "# [Unresolved 3] url; header:Accept; cookie:sid" in output
