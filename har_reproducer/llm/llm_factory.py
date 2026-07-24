from typing import ClassVar, Optional, Type

from langchain_core.language_models.chat_models import BaseChatModel

from har_reproducer.contracts import ProviderRegistry
from har_reproducer.llm.llm_provider import LLMProvider
from har_reproducer.models import LLMSettings


class LLMFactory:
    _registry: ClassVar[ProviderRegistry] = {}

    @classmethod
    def register(cls, provider_cls: Type[LLMProvider]) -> Type[LLMProvider]:
        for name in provider_cls.names:
            cls._registry[name.lower()] = provider_cls
        return provider_cls

    @classmethod
    def get_provider(cls, config: LLMSettings) -> LLMProvider:
        key: str = config.provider.lower()
        provider_cls: Optional[Type[LLMProvider]] = cls._registry.get(key)
        if provider_cls is None:
            raise ValueError(
                f"Unknown LLM provider '{config.provider}'. "
                f"Supported providers: {sorted(cls._registry)}"
            )
        return provider_cls(config)

    @classmethod
    def create(cls, config: LLMSettings) -> BaseChatModel:
        return cls.get_provider(config).create()
