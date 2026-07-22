from .analysis import FailureContext, StepAnalysis
from .config import LLMSettings, ProjectConfig
from .criteria import (
    BodyContainsCriterion,
    CompositeCriterion,
    HtmlElementPresentCriterion,
    StatusCodeCriterion,
    SuccessCriterion,
    UrlMatchCriterion,
)
from .http import Step, StepRequest, StepResponse
from .session import (
    AgentType,
    DynamicToken,
    Extractor,
    SessionState,
    TokenLocation,
    TokenTrace,
)

# CompositeCriterion referencia SuccessCriterion recursivamente (Annotated/Union
# definido em criteria.py); ProjectConfig referencia SuccessCriterion vindo de
# outro módulo (config.py). Em ambos os casos o forward ref só resolve depois
# que todos os modelos envolvidos já foram importados — por isso o rebuild
# fica centralizado aqui, e não junto da definição de cada classe.
CompositeCriterion.model_rebuild()
ProjectConfig.model_rebuild()

__all__ = [
    "AgentType",
    "BodyContainsCriterion",
    "CompositeCriterion",
    "DynamicToken",
    "Extractor",
    "FailureContext",
    "HtmlElementPresentCriterion",
    "LLMSettings",
    "ProjectConfig",
    "SessionState",
    "Step",
    "StepAnalysis",
    "StepRequest",
    "StepResponse",
    "StatusCodeCriterion",
    "SuccessCriterion",
    "TokenLocation",
    "TokenTrace",
    "UrlMatchCriterion",
]
