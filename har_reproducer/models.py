from typing import Dict, List, Optional, Union, Any, Literal
from pydantic import BaseModel, Field

class StepRequest(BaseModel):
    url: str
    method: str
    headers: Dict[str, str] = Field(default_factory=dict)
    cookies: Dict[str, str] = Field(default_factory=dict)
    body: Optional[Union[str, bytes]] = None
    is_skippable: bool = False

class StepResponse(BaseModel):
    status_code: int
    headers: Dict[str, str] = Field(default_factory=dict)
    cookies: Dict[str, str] = Field(default_factory=dict)
    body: Optional[Union[str, bytes]] = None
    body_mime: Optional[str] = None
    redirect_url: Optional[str] = None

class Step(BaseModel):
    index: int
    request: StepRequest
    response: Optional[StepResponse] = None

class ExtractorMetadata(BaseModel):
    token_id: str
    agent_type: str
    verified: bool = False

class Extractor(BaseModel):
    token_id: str
    code: str
    verified: bool = False
    agent_type: Literal["CookieAgent", "HeaderAgent", "JSONPathAgent", "CSSAgent", "RegexAgent"]
    origin_step: Optional[int] = None

TokenLocation = Literal["Header", "Cookie", "BodyJSON", "BodyHTML", "Script"]

class DynamicToken(BaseModel):
    token_id: str
    baseline_value: Optional[str] = None
    current_value: str
    location: TokenLocation
    origin_step: int
    status: Literal["Resolved", "Unresolved"]

class SessionState(BaseModel):
    tokens: Dict[str, str] = Field(default_factory=dict)
    registry: Dict[str, Extractor] = Field(default_factory=dict)

class StepAnalysis(BaseModel):
    step_index: int
    static_values: Dict[str, Any] = Field(default_factory=dict)
    dynamic_tokens: List[DynamicToken] = Field(default_factory=list)
    curl_template: str

class SuccessCriterion(BaseModel):
    type: Literal["url_match", "status_code", "body_contains", "html_element_present", "composite"]
    value: Any
    expected: Any

class FailureContext(BaseModel):
    failed_step: int
    request_attempted: StepRequest
    response_received: StepResponse
    session_snapshot: SessionState
    active_extractors: List[Extractor]

PatchAction = Literal["FIX_EXTRACTOR", "INJECT_VALUE", "REPLACE_EXTRACTOR"]

class Patch(BaseModel):
    action: PatchAction
    target_token_id: Optional[str] = None
    new_value: Optional[str] = None
    new_code: Optional[str] = None
    rationale: str
