from typing import Dict, Optional, List
from pydantic import BaseModel, Field

class TokenTrace(BaseModel):
    """
    Maps a specific value in the request to its source.
    """
    token_id: str
    value: str
    origin_step: int
    location: str  # Header, Cookie, or Body
    key: str  # The header name or cookie name where the token was used

class RecordedRequest(BaseModel):
    """
    Represents a captured HTTP interaction for reproduction.
    """
    step_index: int
    url: str
    method: str
    headers: Dict[str, str] = Field(default_factory=dict)
    cookies: Dict[str, str] = Field(default_factory=dict)
    body: Optional[str] = None
    token_traces: List[TokenTrace] = Field(default_factory=list)
