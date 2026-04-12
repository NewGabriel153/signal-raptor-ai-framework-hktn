from __future__ import annotations

from app.adapters.base import BaseLLMAdapter, LLMAdapterError
from app.core.config import settings

# Known model prefixes -> adapter class.  New providers are registered here.
_GEMINI_PREFIXES = ("gemini-",)
_OPENAI_PREFIXES = ("gpt-", "o1-", "o3-", "o4-")
_ANTHROPIC_PREFIXES = ("claude-",)

_SUPPORTED_HINT = (
    "Supported prefixes: gemini-*, gpt-*, o1-*, o3-*, o4-*, claude-*. "
    "To add a new provider, implement a BaseLLMAdapter subclass and "
    "register it in adapter_factory.py."
)


def create_adapter(model: str, *, api_key: str | None = None) -> BaseLLMAdapter:
    """Instantiate the correct :class:`BaseLLMAdapter` for *model*.

    The factory uses a lazy import so that provider-specific SDK
    dependencies are only loaded when actually needed.
    """
    normalised = model.lower().strip()

    # ── Gemini ─────────────────────────────────────────────────────────
    if normalised.startswith(_GEMINI_PREFIXES):
        from app.adapters.gemini import GeminiAdapter

        key = api_key or settings.GOOGLE_API_KEY
        if not key:
            raise LLMAdapterError(
                f"GOOGLE_API_KEY is required to use model '{model}'. "
                "Set it as an environment variable or pass it explicitly."
            )
        return GeminiAdapter(api_key=key, model=model)

    # ── OpenAI ─────────────────────────────────────────────────────────
    if normalised.startswith(_OPENAI_PREFIXES):
        from app.adapters.openai import OpenAIAdapter

        key = api_key or settings.OPENAI_API_KEY
        if not key:
            raise LLMAdapterError(
                f"OPENAI_API_KEY is required to use model '{model}'. "
                "Set it as an environment variable or pass it explicitly."
            )
        return OpenAIAdapter(api_key=key, model=model)

    # ── Anthropic ──────────────────────────────────────────────────────
    if normalised.startswith(_ANTHROPIC_PREFIXES):
        from app.adapters.anthropic import AnthropicAdapter

        key = api_key or settings.ANTHROPIC_API_KEY
        if not key:
            raise LLMAdapterError(
                f"ANTHROPIC_API_KEY is required to use model '{model}'. "
                "Set it as an environment variable or pass it explicitly."
            )
        return AnthropicAdapter(api_key=key, model=model)

    raise LLMAdapterError(f"Unsupported model: '{model}'. {_SUPPORTED_HINT}")
