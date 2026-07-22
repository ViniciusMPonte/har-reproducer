from typing import Callable, Dict, Protocol, Tuple, Type, TypeAlias

from langchain_core.language_models.chat_models import BaseChatModel

from ..models import Step, StepRequest, StepResponse

StepExecutor: TypeAlias = Callable[[Step], Tuple[StepRequest, StepResponse]]

class LLMProviderProtocol(Protocol):
    def create(self) -> BaseChatModel: ...

ProviderRegistry: TypeAlias = Dict[str, Type[LLMProviderProtocol]]
