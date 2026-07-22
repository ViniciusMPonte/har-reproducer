from typing import Dict, List

from pydantic import BaseModel, Field

from .session import DynamicToken


class StepAnalysis(BaseModel):
    step_index: int
    static_values: Dict[str, str] = Field(default_factory=dict)
    dynamic_tokens: List[DynamicToken] = Field(default_factory=list)
    curl_template: str
