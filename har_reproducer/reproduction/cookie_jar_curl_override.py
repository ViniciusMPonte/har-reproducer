import shlex
from typing import ClassVar, Dict, List, Optional

from har_reproducer.session import CookieJar


class CookieJarCurlOverride:
    COOKIE_FLAG: ClassVar[str] = "--cookie"
    LINE_CONTINUATION_ARTIFACT: ClassVar[str] = "\n"

    def __init__(self, cookie_jar: CookieJar) -> None:
        self.cookie_jar: CookieJar = cookie_jar

    def apply(self, curl_resolved: str, host: str, port: int, path: str) -> str:
        jar_cookies: Dict[str, str] = self.cookie_jar.current(host, port, path)
        if not jar_cookies:
            return curl_resolved

        tokens: List[str] = self._tokenize(curl_resolved)
        existing: Dict[str, str] = self._parse_cookie_tokens(tokens)
        merged: Dict[str, str] = {**existing, **jar_cookies}
        rebuilt: List[str] = self._replace_or_append_cookie_tokens(tokens, merged)
        return shlex.join(rebuilt)

    def _tokenize(self, curl_resolved: str) -> List[str]:
        return [token for token in shlex.split(curl_resolved) if token != self.LINE_CONTINUATION_ARTIFACT]

    def _parse_cookie_tokens(self, tokens: List[str]) -> Dict[str, str]:
        index: Optional[int] = self._cookie_flag_index(tokens)
        if index is None:
            return {}
        return self._parse_cookie_string(tokens[index + 1])

    def _cookie_flag_index(self, tokens: List[str]) -> Optional[int]:
        return tokens.index(self.COOKIE_FLAG) if self.COOKIE_FLAG in tokens else None

    @staticmethod
    def _parse_cookie_string(cookie_string: str) -> Dict[str, str]:
        pairs: Dict[str, str] = {}
        for part in cookie_string.split(";"):
            if "=" not in part:
                continue
            key, value = part.strip().split("=", 1)
            pairs[key] = value
        return pairs

    @staticmethod
    def _format_cookie_string(cookies: Dict[str, str]) -> str:
        return "; ".join(f"{key}={value}" for key, value in cookies.items())

    def _replace_or_append_cookie_tokens(self, tokens: List[str], merged: Dict[str, str]) -> List[str]:
        formatted: str = self._format_cookie_string(merged)
        index: Optional[int] = self._cookie_flag_index(tokens)
        if index is None:
            return tokens + [self.COOKIE_FLAG, formatted]
        return tokens[:index + 1] + [formatted] + tokens[index + 2:]
