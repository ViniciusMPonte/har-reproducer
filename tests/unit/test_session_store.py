from har_reproducer.session.session_store import SessionStore


def test_set_token_and_get_token_round_trip() -> None:
    store: SessionStore = SessionStore()

    store.set_token("abc123", "v1")

    assert store.get_token("abc123") == "v1"


def test_render_substitutes_known_token() -> None:
    store: SessionStore = SessionStore()
    store.set_token("abc123", "tok")

    rendered: str = store.render("Bearer {{extractor:abc123}}")

    assert rendered == "Bearer tok"


def test_render_preserves_placeholder_for_unknown_token() -> None:
    store: SessionStore = SessionStore()

    rendered: str = store.render("{{extractor:naoexiste}}")

    assert rendered == "{{extractor:naoexiste}}"


def test_render_dict_recurses_into_nested_structures() -> None:
    store: SessionStore = SessionStore()
    store.set_token("abc", "V")

    rendered: object = store.render_dict({"a": ["{{extractor:abc}}", 3], "b": {"c": "{{extractor:abc}}"}})

    assert rendered == {"a": ["V", 3], "b": {"c": "V"}}
