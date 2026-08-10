from typing import Callable, Dict, Protocol, Type, TypeAlias, Optional

from langchain_core.language_models.chat_models import BaseChatModel

Strategy: TypeAlias = Callable[[Optional[str]], Optional[str]]

class LLMProviderProtocol(Protocol):
    def create(self) -> BaseChatModel: ...

ProviderRegistry: TypeAlias = Dict[str, Type[LLMProviderProtocol]]
