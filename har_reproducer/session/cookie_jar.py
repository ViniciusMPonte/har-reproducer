from http import cookiejar
from typing import Dict, NamedTuple

from har_reproducer.models import CookieAttributes


class CookieScope(NamedTuple):
    domain: str
    port: int
    path: str


class CookieJar:
    def __init__(self) -> None:
        self._cookies_by_scope: Dict[CookieScope, Dict[str, str]] = {}

    def reset(self) -> None:
        self._cookies_by_scope.clear()

    def feed(
            self, response_host: str, response_port: int,
            cookies: Dict[str, str], attributes: Dict[str, CookieAttributes],
    ) -> None:
        for name, value in cookies.items():
            attrs: CookieAttributes = attributes.get(name, CookieAttributes())
            scope: CookieScope = CookieScope(
                domain=attrs.domain or response_host, port=response_port, path=attrs.path,
            )
            if attrs.expired:
                self._cookies_by_scope.get(scope, {}).pop(name, None)
            else:
                self._cookies_by_scope.setdefault(scope, {})[name] = value

    def current(self, request_host: str, request_port: int, request_path: str) -> Dict[str, str]:
        merged: Dict[str, str] = {}
        for scope, cookies in self._cookies_by_scope.items():
            if self._matches(scope, request_host, request_port, request_path):
                merged.update(cookies)
        return merged

    @staticmethod
    def _matches(scope: CookieScope, request_host: str, request_port: int, request_path: str) -> bool:
        return (
            scope.port == request_port
            and CookieJar._domain_match(request_host, scope.domain)
            and request_path.startswith(scope.path)
        )

    @staticmethod
    def _domain_match(host: str, cookie_domain: str) -> bool:
        if cookiejar.domain_match(host, cookie_domain):
            return True
        return cookiejar.domain_match(host, cookie_domain.strip("."))
