from .llm_factory import LLMFactory
from .llm_provider import LLMProvider


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
