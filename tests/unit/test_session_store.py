from har_reproducer.session.session_store import SessionStore


def test_set_token_stores_value_in_state() -> None:
    store: SessionStore = SessionStore()

    store.set_token("abc123", "v1")

    assert store.state.tokens["abc123"] == "v1"


def test_render_substitutes_known_token() -> None:
    store: SessionStore = SessionStore()
    store.set_token("abc123", "tok")

    rendered: str = store.render("Bearer {{extractor:abc123}}")

    assert rendered == "Bearer tok"


def test_render_preserves_placeholder_for_unknown_token() -> None:
    store: SessionStore = SessionStore()

    rendered: str = store.render("{{extractor:naoexiste}}")

    assert rendered == "{{extractor:naoexiste}}"
