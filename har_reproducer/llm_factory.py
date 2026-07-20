"""
LLM factory for the token extraction agents.

Wraps LangChain's ``init_chat_model`` so the rest of the codebase can request a
chat model by provider name (``"ollama"``, ``"anthropic"``, ``"openai"``, ...)
without knowing the concrete integration class. This keeps the LLM fallback of
the extractor agents provider-agnostic and easily extensible.
"""
from typing import Any, Dict

from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel

from .models import LLMSettings


def create_llm(config: LLMSettings) -> BaseChatModel:
    """Build a LangChain chat model from an :class:`LLMSettings`.

    Uses ``init_chat_model`` under the hood, which natively supports several
    providers via a simple string-based configuration. Any provider not handled
    explicitly here still works as long as LangChain supports it.
    """
    kwargs: Dict[str, Any] = dict(config.extra)
    if config.temperature is not None:
        kwargs.setdefault("temperature", config.temperature)

    return init_chat_model(config.model, model_provider=config.provider, **kwargs)
