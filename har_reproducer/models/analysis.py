from typing import Dict, List

from pydantic import BaseModel, Field

from .http import StepRequest, StepResponse
from .session import DynamicToken, Extractor, SessionState


class StepAnalysis(BaseModel):
    step_index: int
    static_values: Dict[str, str] = Field(default_factory=dict)
    dynamic_tokens: List[DynamicToken] = Field(default_factory=list)
    curl_template: str


class FailureContext(BaseModel):
    failed_step: int
    request_attempted: StepRequest
    response_received: StepResponse
    session_snapshot: SessionState
    active_extractors: List[Extractor]
