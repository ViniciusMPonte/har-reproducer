import os
from abc import ABC
from typing import Any, Dict, Optional, Type

from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel

from .contracts import ProviderRegistry
from .models import LLMSettings


class LLMProvider(ABC):
    names: tuple[str, ...] = ()
    langchain_provider: str = ""
    api_key_env: Optional[str] = None

    def __init__(self, config: LLMSettings) -> None:
        self.config: LLMSettings = config

    def _build_kwargs(self) -> Dict[str, Any]:
        kwargs: Dict[str, Any] = dict(self.config.extra)
        if self.config.temperature is not None:
            kwargs.setdefault("temperature", self.config.temperature)
        return kwargs

    def _check_api_key(self) -> None:
        if self.api_key_env and not os.environ.get(self.api_key_env):
            raise ValueError(
                f"Missing API key for provider '{self.config.provider}': "
                f"environment variable '{self.api_key_env}' is not set. "
                f"Add it to your .env file."
            )

    def create(self) -> BaseChatModel:
        self._check_api_key()
        return init_chat_model(
            self.config.model,
            model_provider=self.langchain_provider,
            **self._build_kwargs(),
        )


class LLMFactory:
    _registry: ProviderRegistry = {}

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


@LLMFactory.register
class OllamaProvider(LLMProvider):
    names = ("ollama",)
    langchain_provider = "ollama"
    api_key_env = None


@LLMFactory.register
class GoogleProvider(LLMProvider):
    names = ("google", "gemini", "gemma", "google_genai")
    langchain_provider = "google_genai"
    api_key_env = "GOOGLE_API_KEY"


@LLMFactory.register
class OpenAIProvider(LLMProvider):
    names = ("openai",)
    langchain_provider = "openai"
    api_key_env = "OPENAI_API_KEY"


@LLMFactory.register
class AnthropicProvider(LLMProvider):
    names = ("anthropic", "claude")
    langchain_provider = "anthropic"
    api_key_env = "ANTHROPIC_API_KEY"