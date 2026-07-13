from enum import Enum
from typing import Annotated, Dict, List, Optional, Union, Literal

from pydantic import BaseModel, Field


class AgentType(str, Enum):
    COOKIE = "CookieAgent"
    HEADER = "HeaderAgent"
    JSONPATH = "JSONPathAgent"
    CSS = "CSSAgent"
    REGEX = "RegexAgent"


class PatchAction(str, Enum):
    FIX_EXTRACTOR = "FIX_EXTRACTOR"
    INJECT_VALUE = "INJECT_VALUE"
    REPLACE_EXTRACTOR = "REPLACE_EXTRACTOR"


class TokenLocation(str, Enum):
    HEADER = "Header"
    COOKIE = "Cookie"
    BODY_JSON = "BodyJSON"
    BODY_HTML = "BodyHTML"
    SCRIPT = "Script"


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


class TokenTrace(BaseModel):
    token_id: str
    value: str
    origin_step: int
    location: TokenLocation
    key: str


class Extractor(BaseModel):
    token_id: str
    code: str
    verified: bool = False
    agent_type: AgentType
    origin_step: Optional[int] = None


class DynamicToken(BaseModel):
    token_id: str
    current_value: str
    destination_location: TokenLocation
    origin_location: Optional[TokenLocation] = None
    origin_step: Optional[int] = None
    status: Literal["Resolved", "Unresolved"]


class SessionState(BaseModel):
    tokens: Dict[str, str] = Field(default_factory=dict)
    registry: Dict[str, Extractor] = Field(default_factory=dict)


class StepAnalysis(BaseModel):
    step_index: int
    static_values: Dict[str, str] = Field(default_factory=dict)
    dynamic_tokens: List[DynamicToken] = Field(default_factory=list)
    curl_template: str


class StatusCodeCriterion(BaseModel):
    type: Literal["status_code"]
    expected: int


class BodyContainsCriterion(BaseModel):
    type: Literal["body_contains"]
    expected: str


class UrlMatchCriterion(BaseModel):
    type: Literal["url_match"]
    expected: str


class HtmlElementPresentCriterion(BaseModel):
    type: Literal["html_element_present"]
    expected: str


class CompositeCriterion(BaseModel):
    type: Literal["composite"]
    expected: List["SuccessCriterion"]


SuccessCriterion = Annotated[
    Union[
        StatusCodeCriterion,
        BodyContainsCriterion,
        UrlMatchCriterion,
        HtmlElementPresentCriterion,
        CompositeCriterion,
    ],
    Field(discriminator="type"),
]

# Required for CompositeCriterion's self-referential List["SuccessCriterion"]
CompositeCriterion.model_rebuild()


class FailureContext(BaseModel):
    failed_step: int
    request_attempted: StepRequest
    response_received: StepResponse
    session_snapshot: SessionState
    active_extractors: List[Extractor]


class InjectValuePatch(BaseModel):
    action: Literal[PatchAction.INJECT_VALUE]
    target_token_id: str
    new_value: str
    rationale: str


class FixExtractorPatch(BaseModel):
    action: Literal[PatchAction.FIX_EXTRACTOR]
    target_token_id: str
    new_code: str
    rationale: str


class ReplaceExtractorPatch(BaseModel):
    action: Literal[PatchAction.REPLACE_EXTRACTOR]
    target_token_id: str
    new_code: str
    rationale: str


Patch = Annotated[
    Union[InjectValuePatch, FixExtractorPatch, ReplaceExtractorPatch],
    Field(discriminator="action"),
]
