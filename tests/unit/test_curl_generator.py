from typing import Optional

from har_reproducer.models import DynamicToken, StepRequest, TokenLocation
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


def test_generate_without_commentable_tokens_returns_only_curl_block() -> None:
    generator: CurlGenerator = CurlGenerator()
    request: StepRequest = StepRequest(url="https://x", method="GET")

    output: str = generator.generate(request, [_token(None, None)])

    assert output.startswith("curl -X GET")


def test_generate_adds_undetermined_location_comment() -> None:
    generator: CurlGenerator = CurlGenerator()
    request: StepRequest = StepRequest(url="https://x", method="GET")

    output: str = generator.generate(request, [_token(2, None)])

    assert "# Token abc comes from response of step 2" in output
    assert "origin location undetermined" in output


def test_generate_adds_extraction_exhausted_comment() -> None:
    generator: CurlGenerator = CurlGenerator()
    request: StepRequest = StepRequest(url="https://x", method="GET")

    output: str = generator.generate(request, [_token(2, TokenLocation.COOKIE, extraction_exhausted=True)])

    assert "# Token abc comes from response of step 2" in output
    assert "extraction exhausted" in output


def test_generate_omits_cookie_flag_when_no_cookies() -> None:
    generator: CurlGenerator = CurlGenerator()
    request: StepRequest = StepRequest(url="https://x", method="GET")

    output: str = generator.generate(request, [])

    assert "--cookie" not in output


def test_generate_includes_body_flag_with_payload() -> None:
    generator: CurlGenerator = CurlGenerator()
    request: StepRequest = StepRequest(url="https://x", method="POST", body="payload")

    output: str = generator.generate(request, [])

    assert "--data-binary" in output
    assert "payload" in output
