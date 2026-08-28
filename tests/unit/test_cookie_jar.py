from typing import Dict

from har_reproducer.models import CookieAttributes
from har_reproducer.session import CookieJar


def test_current_returns_cookie_fed_for_matching_scope() -> None:
    jar: CookieJar = CookieJar()

    jar.feed("exemplo.com", 443, {"a": "1"}, {})

    assert jar.current("exemplo.com", 443, "/") == {"a": "1"}


def test_current_matches_domain_cookie_on_subdomain_base_domain_and_rejects_other_host_and_port() -> None:
    jar: CookieJar = CookieJar()
    attributes: Dict[str, CookieAttributes] = {"a": CookieAttributes(domain=".exemplo.com")}

    jar.feed("exemplo.com", 443, {"a": "1"}, attributes)

    assert jar.current("sub.exemplo.com", 443, "/") == {"a": "1"}
    assert jar.current("exemplo.com", 443, "/") == {"a": "1"}
    assert jar.current("outro.com", 443, "/") == {}
    assert jar.current("exemplo.com", 8443, "/") == {}


def test_feed_with_expired_attribute_removes_cookie_from_matching_scope() -> None:
    jar: CookieJar = CookieJar()

    jar.feed("exemplo.com", 443, {"a": "1"}, {})
    jar.feed("exemplo.com", 443, {"a": "1"}, {"a": CookieAttributes(expired=True)})

    assert jar.current("exemplo.com", 443, "/") == {}


def test_current_for_never_fed_scope_returns_empty_dict_without_raising() -> None:
    jar: CookieJar = CookieJar()

    assert jar.current("nunca-alimentado.com", 443, "/") == {}


def test_reset_clears_all_state() -> None:
    jar: CookieJar = CookieJar()

    jar.feed("exemplo.com", 443, {"a": "1"}, {})
    jar.reset()

    assert jar.current("exemplo.com", 443, "/") == {}


def test_current_matches_path_by_prefix() -> None:
    jar: CookieJar = CookieJar()

    jar.feed("exemplo.com", 443, {"a": "1"}, {"a": CookieAttributes(path="/")})

    assert jar.current("exemplo.com", 443, "/admin") == {"a": "1"}


def test_domain_match_is_ported_from_stickycookie_not_raw_cookiejar_domain_match() -> None:
    from http import cookiejar

    assert cookiejar.domain_match("exemplo.com", ".exemplo.com") is False

    jar: CookieJar = CookieJar()
    attributes: Dict[str, CookieAttributes] = {"a": CookieAttributes(domain=".exemplo.com")}

    jar.feed("exemplo.com", 443, {"a": "1"}, attributes)

    assert jar.current("exemplo.com", 443, "/") == {"a": "1"}
