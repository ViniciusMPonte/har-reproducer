import re


class IdentifierSanitizer:
    @staticmethod
    def sanitize(raw: str) -> str:
        sanitized: str = re.sub(r"\W", "_", str(raw))
        return f"t_{sanitized}" if sanitized else "token"
