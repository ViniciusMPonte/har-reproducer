from typing import Dict, List, Optional

from har_reproducer.models import AgentType, DynamicToken, Extractor, StepRequest, TokenLocation
from har_reproducer.replay.curl_token_comment import CurlTokenComment
from har_reproducer.reproduction.curl_generator import CurlGenerator
from har_reproducer.session import SessionStore


def _extractor(token_id: str, agent_type: AgentType) -> Extractor:
    return Extractor(token_id=token_id, code="value", agent_type=agent_type)


def _session_store(registry: Dict[str, Extractor]) -> SessionStore:
    session_store: SessionStore = SessionStore()
    session_store.state.registry.update(registry)
    return session_store


def _generator(session_store: SessionStore) -> CurlGenerator:
    return CurlGenerator(CurlTokenComment(step_index_width=4), session_store)


def _token(origin_step: Optional[int]) -> DynamicToken:
    return DynamicToken(
        token_id="abc",
        path="header:X",
        current_value="v",
        destination_location=TokenLocation.HEADER,
        origin_step=origin_step,
        status="NotFound" if origin_step is None else "Resolved",
    )


def test_generate_without_commentable_tokens_reports_them_as_unresolved() -> None:
    generator: CurlGenerator = _generator(_session_store({}))
    request: StepRequest = StepRequest(url="https://x", method="GET")

    lines: List[str] = generator.generate(request, [_token(None)]).splitlines()

    assert lines[0] == "# [Unresolved 1] header:X"
    assert lines[1].startswith("curl -X GET")


def test_generate_adds_undetermined_location_comment() -> None:
    session_store: SessionStore = _session_store({"abc": _extractor("abc", AgentType.LITERAL)})
    generator: CurlGenerator = _generator(session_store)
    request: StepRequest = StepRequest(url="https://x", method="GET")

    output: str = generator.generate(request, [_token(2)])

    assert "# [Token abc comes from response of step 0002]" in output
    assert "origin location undetermined" in output


def test_generate_adds_extraction_exhausted_comment() -> None:
    session_store: SessionStore = _session_store({"abc": _extractor("abc", AgentType.LITERAL_FALLBACK)})
    generator: CurlGenerator = _generator(session_store)
    request: StepRequest = StepRequest(url="https://x", method="GET")

    output: str = generator.generate(request, [_token(2)])

    assert "# [Token abc comes from response of step 0002]" in output
    assert "extraction exhausted" in output


def test_generate_omits_dependency_phrase_for_a_deterministic_cache_hit_extractor() -> None:
    session_store: SessionStore = _session_store({"abc": _extractor("abc", AgentType.HEADER)})
    generator: CurlGenerator = _generator(session_store)
    request: StepRequest = StepRequest(url="https://x", method="GET")

    output: str = generator.generate(request, [_token(2)])

    assert output.splitlines()[0] == "# [Token abc comes from response of step 0002]"


def test_generate_omits_cookie_flag_when_no_cookies() -> None:
    generator: CurlGenerator = _generator(_session_store({}))
    request: StepRequest = StepRequest(url="https://x", method="GET")

    output: str = generator.generate(request, [])

    assert "--cookie" not in output


def test_generate_includes_body_flag_with_payload() -> None:
    generator: CurlGenerator = _generator(_session_store({}))
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
        status="NotFound" if origin_step is None else "Resolved",
    )


def test_generate_appends_unresolved_line_after_the_dependency_lines() -> None:
    session_store: SessionStore = _session_store({"abc": _extractor("abc", AgentType.HEADER)})
    generator: CurlGenerator = _generator(session_store)
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
    session_store: SessionStore = _session_store({"abc": _extractor("abc", AgentType.HEADER)})
    generator: CurlGenerator = _generator(session_store)
    request: StepRequest = StepRequest(url="https://x", method="GET")

    output: str = generator.generate(request, [_token_with_path(3, "header:X-Csrf")])

    assert "Unresolved" not in output
    assert "# [Token abc comes from response of step 0003]" in output


def test_generate_with_only_unresolved_tokens_emits_a_single_comment_line() -> None:
    generator: CurlGenerator = _generator(_session_store({}))
    request: StepRequest = StepRequest(url="https://x", method="GET")
    tokens: List[DynamicToken] = [_token_with_path(None, "header:Accept"), _token_with_path(None, "url")]

    lines: List[str] = generator.generate(request, tokens).splitlines()

    assert lines[0] == "# [Unresolved 2] header:Accept; url"
    assert lines[1].startswith("curl -X GET")


def test_generate_with_empty_token_list_has_no_comment() -> None:
    generator: CurlGenerator = _generator(_session_store({}))
    request: StepRequest = StepRequest(url="https://x", method="GET")

    output: str = generator.generate(request, [])

    assert output.startswith("curl -X GET")
    assert "#" not in output


def _static_token(origin_step: int, path: str) -> DynamicToken:
    return DynamicToken(
        token_id="abc",
        path=path,
        current_value="v",
        destination_location=TokenLocation.HEADER,
        origin_step=origin_step,
        status="Static",
    )


def test_generate_omits_dependency_line_for_a_static_token_and_emits_static_line() -> None:
    generator: CurlGenerator = _generator(_session_store({}))
    request: StepRequest = StepRequest(url="https://x", method="GET")

    output: str = generator.generate(request, [_static_token(23, "header:Content-Type")])

    assert "# [Token" not in output
    assert "# [Static 1] header:Content-Type←0023" in output


def test_generate_mixes_resolved_and_static_tokens_in_separate_lines() -> None:
    session_store: SessionStore = _session_store({"abc": _extractor("abc", AgentType.HEADER)})
    generator: CurlGenerator = _generator(session_store)
    request: StepRequest = StepRequest(url="https://x", method="GET")
    tokens: List[DynamicToken] = [
        _static_token(1, "header:X"),
        _static_token(2, "header:Y"),
        _token_with_path(3, "header:X-Csrf"),
    ]

    lines: List[str] = generator.generate(request, tokens).splitlines()

    assert lines[0] == "# [Token abc comes from response of step 0003]"
    assert lines[1] == "# [Static 2] header:X←0001; header:Y←0002"
    assert lines[2].startswith("curl -X GET")


def test_generate_keeps_unresolved_tokens_separate_from_static_tokens() -> None:
    generator: CurlGenerator = _generator(_session_store({}))
    request: StepRequest = StepRequest(url="https://x", method="GET")
    tokens: List[DynamicToken] = [
        _static_token(1, "header:X"),
        _token_with_path(None, "header:Accept"),
    ]

    output: str = generator.generate(request, tokens)

    assert "# [Static 1] header:X←0001" in output
    assert "# [Unresolved 1] header:Accept" in output


def test_unresolved_line_keeps_the_order_of_the_received_tokens() -> None:
    generator: CurlGenerator = _generator(_session_store({}))
    request: StepRequest = StepRequest(url="https://x", method="GET")
    tokens: List[DynamicToken] = [
        _token_with_path(None, "url"),
        _token_with_path(None, "header:Accept"),
        _token_with_path(None, "cookie:sid"),
    ]

    output: str = generator.generate(request, tokens)

    assert "# [Unresolved 3] url; header:Accept; cookie:sid" in output
