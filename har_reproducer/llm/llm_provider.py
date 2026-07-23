import os
from abc import ABC
from typing import Any, ClassVar, Dict, Optional, Tuple

from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel

from ..models import LLMSettings


class LLMProvider(ABC):

    names: ClassVar[Tuple[str, ...]] = ()
    langchain_provider: ClassVar[str] = ""
    api_key_env: ClassVar[Optional[str]] = None

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
