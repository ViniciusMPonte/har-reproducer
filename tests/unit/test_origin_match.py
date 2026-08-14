from har_reproducer.models import DynamicToken, OriginContainer, OriginMatch, TokenLocation


def test_origin_match_defaults_key_and_container_to_none() -> None:
    match: OriginMatch = OriginMatch(step_index=7)

    assert match.step_index == 7
    assert match.origin_key is None
    assert match.origin_container is None


def test_origin_match_preserves_key_and_container() -> None:
    match: OriginMatch = OriginMatch(step_index=7, origin_key="ETag", origin_container=OriginContainer.HEADER)

    assert match.step_index == 7
    assert match.origin_key == "ETag"
    assert match.origin_container is OriginContainer.HEADER


def test_origin_container_is_built_from_its_value() -> None:
    assert OriginContainer("Cookie") is OriginContainer.COOKIE
    assert OriginContainer("Header") is OriginContainer.HEADER


def test_dynamic_token_built_as_existing_call_sites_do_defaults_new_fields_to_none() -> None:
    token: DynamicToken = DynamicToken(
        token_id="abc123",
        path="header:If-None-Match",
        current_value='W/"9b1-abc"',
        destination_location=TokenLocation.HEADER,
        status="UnderReview",
    )

    assert token.origin_key is None
    assert token.origin_container is None


def test_dynamic_token_accepts_origin_key_and_container() -> None:
    token: DynamicToken = DynamicToken(
        token_id="abc123",
        path="header:If-None-Match",
        current_value='W/"9b1-abc"',
        destination_location=TokenLocation.HEADER,
        origin_step=3,
        origin_key="ETag",
        origin_container=OriginContainer.HEADER,
        status="Resolved",
    )

    assert token.origin_key == "ETag"
    assert token.origin_container is OriginContainer.HEADER
