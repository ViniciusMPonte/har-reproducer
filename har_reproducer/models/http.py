from typing import Dict, Optional, Union
from pydantic import BaseModel, Field

from har_reproducer.models.analysis import StepAnalysis


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
    analysis: Optional[StepAnalysis] = None