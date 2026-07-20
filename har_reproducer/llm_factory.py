"""
LLM factory for the token extraction agents.

Wraps LangChain's ``init_chat_model`` so the rest of the codebase can request a
chat model by provider name (``"ollama"``, ``"anthropic"``, ``"openai"``, ...)
without knowing the concrete integration class. This keeps the LLM fallback of
the extractor agents provider-agnostic and easily extensible.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel


@dataclass
class LLMConfig:
    """Declarative configuration for a chat model.

    Attributes:
        model: The model name (e.g. ``"llama3"``, ``"claude-3-5-sonnet-latest"``).
        provider: The LangChain provider string (e.g. ``"ollama"``, ``"anthropic"``).
        temperature: Sampling temperature. ``0.0`` keeps generation deterministic.
        extra: Additional keyword arguments forwarded to ``init_chat_model``.
    """

    model: str
    provider: str = "ollama"
    temperature: Optional[float] = 0.0
    extra: Dict[str, Any] = field(default_factory=dict)


def create_llm(config: LLMConfig) -> BaseChatModel:
    """Build a LangChain chat model from an :class:`LLMConfig`.

    Uses ``init_chat_model`` under the hood, which natively supports several
    providers via a simple string-based configuration. Any provider not handled
    explicitly here still works as long as LangChain supports it.
    """
    kwargs: Dict[str, Any] = dict(config.extra)
    if config.temperature is not None:
        kwargs.setdefault("temperature", config.temperature)

    return init_chat_model(config.model, model_provider=config.provider, **kwargs)
