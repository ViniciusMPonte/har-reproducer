from enum import Enum
from typing import Dict, Literal, Optional

from pydantic import BaseModel, Field


class AgentType(str, Enum):
    COOKIE = "CookieAgent"
    HEADER = "HeaderAgent"
    JSONPATH = "JSONPathAgent"
    CSS = "CSSAgent"
    REGEX = "RegexAgent"
    LITERAL = "LiteralAgent"
    LITERAL_FALLBACK = "LiteralFallbackAgent"


class TokenLocation(str, Enum):
    HEADER = "Header"
    COOKIE = "Cookie"
    BODY_JSON = "BodyJSON"
    BODY_HTML = "BodyHTML"
    SCRIPT = "Script"
    URL_PARAM = "UrlParam"


class TokenResolutionStatus(str, Enum):
    STATIC = "static"
    RESOLVED = "resolved"
    CAPTURED_FALLBACK = "captured_fallback"
    UNRESOLVED = "unresolved"


class Extractor(BaseModel):
    token_id: str
    code: str
    verified: bool = False
    agent_type: AgentType
    origin_step: Optional[int] = None
    temp_file_path: Optional[str] = None
    valid_count: int = 0
    last_value: Optional[str] = None
    ever_changed: bool = False
    captured_value: Optional[str] = None


class DynamicToken(BaseModel):
    token_id: str
    path: str
    current_value: str
    destination_location: TokenLocation
    origin_location: Optional[TokenLocation] = None
    origin_step: Optional[int] = None
    status: Literal["UnderReview", "NotFound", "Unresolved", "Resolved"]
    extraction_exhausted: bool = False


class SessionState(BaseModel):
    tokens: Dict[str, str] = Field(default_factory=dict)
    registry: Dict[str, Extractor] = Field(default_factory=dict)
