from har_reproducer.models import CookieAttributes, StepResponse


def test_cookie_attributes_defaults_domain_path_and_expired() -> None:
    attributes: CookieAttributes = CookieAttributes()

    assert attributes.domain is None
    assert attributes.path == "/"
    assert attributes.expired is False


def test_step_response_defaults_cookie_attributes_to_empty_dict() -> None:
    response: StepResponse = StepResponse(status_code=200)

    assert response.cookie_attributes == {}


def test_step_response_json_round_trip_preserves_cookies_and_cookie_attributes() -> None:
    response: StepResponse = StepResponse(
        status_code=200,
        cookies={"a": "1"},
        cookie_attributes={"a": CookieAttributes(domain=".exemplo.com", path="/api", expired=True)},
    )

    serialized: str = response.model_dump_json()

    assert '"cookies"' in serialized
    assert '"cookie_attributes"' in serialized

    restored: StepResponse = StepResponse.model_validate_json(serialized)

    assert restored.cookies == {"a": "1"}
    assert restored.cookie_attributes["a"].domain == ".exemplo.com"
    assert restored.cookie_attributes["a"].path == "/api"
    assert restored.cookie_attributes["a"].expired is True
