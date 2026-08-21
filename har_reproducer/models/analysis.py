from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from har_reproducer.models.session import DynamicToken, OriginContainer


class OriginMatch(BaseModel):
    step_index: int
    origin_key: Optional[str] = None
    origin_container: Optional[OriginContainer] = None
    fragment: Optional[str] = None


class StepAnalysis(BaseModel):
    step_index: int
    static_values: Dict[str, str] = Field(default_factory=dict)
    dynamic_tokens: List[DynamicToken] = Field(default_factory=list)
    curl_template: str
