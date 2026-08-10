import json
import re
from typing import Any, Dict, Optional

from har_reproducer.models import TokenLocation
from har_reproducer.tracking.response_grep import ResponseGrep


class TokenLocationDetector:

    @classmethod
    def find(cls, value: str, response_sample: Dict[str, Any]) -> Optional[TokenLocation]:
        location: Optional[TokenLocation] = cls._find_in_cookies(value, response_sample)
        if location is not None:
            return location

        location = cls._find_in_headers(value, response_sample)
        if location is not None:
            return location

        location = cls._find_in_redirect_url(value, response_sample)
        if location is not None:
            return location

        location = cls._find_in_body(value, response_sample)
        if location is not None:
            return location

        print(f"[AVISO] Não foi possível determinar a origem do token '{value[:30]}...'.")
        return None

    @classmethod
    def _find_in_headers(cls, value: str, response_sample: Dict[str, Any]) -> Optional[TokenLocation]:
        for header_value in response_sample.get("headers", {}).values():
            if cls._value_present(value, header_value):
                return TokenLocation.HEADER
        return None

    @classmethod
    def _find_in_cookies(cls, value: str, response_sample: Dict[str, Any]) -> Optional[TokenLocation]:
        for cookie_value in response_sample.get("cookies", {}).values():
            if cls._value_present(value, cookie_value):
                return TokenLocation.COOKIE
        return None

    @classmethod
    def _find_in_redirect_url(cls, value: str, response_sample: Dict[str, Any]) -> Optional[TokenLocation]:
        redirect_url: Optional[str] = response_sample.get("redirect_url")
        if redirect_url and cls._value_present(value, redirect_url):
            return TokenLocation.URL_PARAM
        return None

    @classmethod
    def _find_in_body(cls, value: str, response_sample: Dict[str, Any]) -> Optional[TokenLocation]:
        body: Optional[str] = response_sample.get("body")
        if not body or not cls._value_present(value, body):
            return None

        mime: str = (response_sample.get("body_mime") or "").lower()

        if cls._is_script_mime(mime):
            return TokenLocation.SCRIPT
        if cls._is_json_mime(mime, body):
            return TokenLocation.BODY_JSON
        if cls._is_html_mime(mime, body):
            return cls._locate_in_html(body, value)
        return None

    @staticmethod
    def _is_script_mime(mime: str) -> bool:
        return "javascript" in mime or "ecmascript" in mime

    @classmethod
    def _is_json_mime(cls, mime: str, body: str) -> bool:
        return "json" in mime or cls._is_valid_json(body)

    @classmethod
    def _is_html_mime(cls, mime: str, body: str) -> bool:
        return "html" in mime or cls._looks_like_html(body)

    @classmethod
    def _locate_in_html(cls, body: str, value: str) -> TokenLocation:
        html_without_scripts: str = cls._strip_script_blocks(body)
        if value in html_without_scripts:
            return TokenLocation.BODY_HTML
        if cls._value_inside_script_tag(body, value):
            return TokenLocation.SCRIPT
        return TokenLocation.BODY_HTML

    @staticmethod
    def _looks_like_html(body: str) -> bool:
        return bool(re.search(r"<html|<!doctype html|<body|<div", body, re.IGNORECASE))

    @staticmethod
    def _strip_script_blocks(body: str) -> str:
        return re.sub(r"<script[^>]*>.*?</script>", "", body, flags=re.DOTALL | re.IGNORECASE)

    @staticmethod
    def _value_inside_script_tag(body: str, value: str) -> bool:
        for match in re.finditer(r"<script[^>]*>(.*?)</script>", body, re.DOTALL | re.IGNORECASE):
            if value in match.group(1):
                return True
        return False

    @staticmethod
    def _is_valid_json(body: str) -> bool:
        try:
            json.loads(body)
            return True
        except (json.JSONDecodeError, TypeError):
            return False

    @classmethod
    def _value_present(cls, value: str, text: str) -> bool:
        return any(variant in text for variant in ResponseGrep.value_variants(value))
