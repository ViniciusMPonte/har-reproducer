from typing import Optional

from har_reproducer.models import AgentType, DynamicToken, Extractor, StepRequest, TokenLocation
from har_reproducer.session import SessionStore
from har_reproducer.tracking.placeholder_applier import PlaceholderApplier


def _token(
        token_id: str,
        value: str,
        location: TokenLocation = TokenLocation.HEADER,
        origin_fragment: Optional[str] = None,
) -> DynamicToken:
    return DynamicToken(
        token_id=token_id,
        path=f"header:{token_id}",
        current_value=value,
        origin_fragment=origin_fragment,
        destination_location=location,
        status="Resolved",
    )


def _register_verified(store: SessionStore, token_id: str) -> None:
    store.state.registry[token_id] = Extractor(
        token_id=token_id, code="def f(r): pass", verified=True, agent_type=AgentType.REGEX
    )


def test_apply_replaces_value_present_in_header() -> None:
    store: SessionStore = SessionStore()
    _register_verified(store, "abc")
    applier: PlaceholderApplier = PlaceholderApplier(store)
    request: StepRequest = StepRequest(url="https://x", method="GET", headers={"X-Token": "abc"})

    applier.apply(request, [_token("abc", "abc")])

    assert request.headers["X-Token"] == "{{extractor:abc}}"


def test_apply_orders_longer_values_first_to_avoid_partial_substring_match() -> None:
    store: SessionStore = SessionStore()
    _register_verified(store, "short")
    _register_verified(store, "long")
    applier: PlaceholderApplier = PlaceholderApplier(store)
    request: StepRequest = StepRequest(url="https://x", method="GET", headers={"X-Token": "abcdef"})

    applier.apply(request, [_token("short", "abc"), _token("long", "abcdef")])

    assert "abcdef" not in request.headers["X-Token"]
    assert request.headers["X-Token"] == "{{extractor:long}}"


def test_apply_skips_token_without_verified_extractor() -> None:
    store: SessionStore = SessionStore()
    applier: PlaceholderApplier = PlaceholderApplier(store)
    request: StepRequest = StepRequest(url="https://x", method="GET", headers={"X-Token": "abc"})

    applier.apply(request, [_token("abc", "abc")])

    assert request.headers["X-Token"] == "abc"


def test_apply_skips_token_with_empty_value() -> None:
    store: SessionStore = SessionStore()
    _register_verified(store, "abc")
    applier: PlaceholderApplier = PlaceholderApplier(store)
    request: StepRequest = StepRequest(url="https://x", method="GET", headers={"X-Token": "abc"})

    applier.apply(request, [_token("abc", "")])

    assert request.headers["X-Token"] == "abc"


def test_apply_replaces_in_utf8_body_bytes() -> None:
    store: SessionStore = SessionStore()
    _register_verified(store, "abc")
    applier: PlaceholderApplier = PlaceholderApplier(store)
    request: StepRequest = StepRequest(url="https://x", method="POST", body=b"token=abc")

    applier.apply(request, [_token("abc", "abc")])

    assert request.body == b"token={{extractor:abc}}"


def test_apply_leaves_non_utf8_body_bytes_untouched() -> None:
    store: SessionStore = SessionStore()
    _register_verified(store, "abc")
    applier: PlaceholderApplier = PlaceholderApplier(store)
    request: StepRequest = StepRequest(url="https://x", method="POST", body=b"\xff\xfe")

    applier.apply(request, [_token("abc", "abc")])

    assert request.body == b"\xff\xfe"


def test_apply_replaces_only_the_fragment_leaving_the_literal_prefix_in_place() -> None:
    store: SessionStore = SessionStore()
    _register_verified(store, "abc")
    applier: PlaceholderApplier = PlaceholderApplier(store)
    request: StepRequest = StepRequest(url="https://x", method="GET", headers={"Authorization": "Bearer eyJxyz"})

    applier.apply(request, [_token("abc", "Bearer eyJxyz", origin_fragment="eyJxyz")])

    assert request.headers["Authorization"] == "Bearer {{extractor:abc}}"


def test_apply_orders_by_fragment_length_not_by_the_full_value_length() -> None:
    store: SessionStore = SessionStore()
    _register_verified(store, "short")
    _register_verified(store, "long")
    applier: PlaceholderApplier = PlaceholderApplier(store)
    request: StepRequest = StepRequest(url="https://x", method="GET", headers={"X-Token": "abcdef"})

    applier.apply(request, [
        _token("short", "abcdef", origin_fragment="abc"),
        _token("long", "abcdef", origin_fragment="abcdef"),
    ])

    assert "abcdef" not in request.headers["X-Token"]
    assert request.headers["X-Token"] == "{{extractor:long}}"
