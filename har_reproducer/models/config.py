from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from har_reproducer.models.criteria import SuccessCriterion


class LLMSettings(BaseModel):
    provider: str = "ollama"
    model: str
    temperature: Optional[float] = 0.0
    extra: Dict[str, Any] = Field(default_factory=dict)


class SkipRulesConfig(BaseModel):
    methods: List[str] = Field(default_factory=lambda: ["OPTIONS"])


class ProjectConfig(BaseModel):
    llm: Optional[LLMSettings] = None
    success_criteria: List[SuccessCriterion] = Field(default_factory=list)
    proxy_port: Optional[int] = None
    ca_cert_path: Optional[Path] = None
    response_reference_dir: Optional[Path] = None
    skip_rules: SkipRulesConfig = Field(default_factory=SkipRulesConfig)
