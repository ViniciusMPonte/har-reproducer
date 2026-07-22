from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from .criteria import SuccessCriterion


class LLMSettings(BaseModel):
    provider: str = "ollama"
    model: str
    temperature: Optional[float] = 0.0
    extra: Dict[str, Any] = Field(default_factory=dict)


class ProjectConfig(BaseModel):
    llm: Optional[LLMSettings] = None
    success_criteria: List[SuccessCriterion] = Field(default_factory=list)
