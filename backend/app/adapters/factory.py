from __future__ import annotations

from app.adapters.base import BaseLLMAdapter, LLMAdapterError
from app.core.config import settings

_SUPPORTED_PROVIDERS = ("openai", "anthropic", "google_genai")


class AdapterFactory:
    """Instantiate provider-specific :class:`BaseLLMAdapter` implementations."""

    @staticmethod
    def get_adapter(provider: str, target_model: str) -> BaseLLMAdapter:
        normalised_provider = provider.strip().lower()
        normalised_model = target_model.strip()

        if not normalised_provider:
            raise LLMAdapterError("LLM provider is required to create an adapter.")
        if not normalised_model:
            raise LLMAdapterError("Target model is required to create an adapter.")

        if normalised_provider == "openai":
            from app.adapters.openai import OpenAIAdapter

            api_key = AdapterFactory._require_api_key(
                settings.OPENAI_API_KEY,
                env_var_name="OPENAI_API_KEY",
                provider=normalised_provider,
                target_model=normalised_model,
            )
            return OpenAIAdapter(api_key=api_key, model=normalised_model)

        if normalised_provider == "anthropic":
            from app.adapters.anthropic import AnthropicAdapter

            api_key = AdapterFactory._require_api_key(
                settings.ANTHROPIC_API_KEY,
                env_var_name="ANTHROPIC_API_KEY",
                provider=normalised_provider,
                target_model=normalised_model,
            )
            return AnthropicAdapter(api_key=api_key, model=normalised_model)

        if normalised_provider == "google_genai":
            from app.adapters.gemini import GeminiAdapter

            api_key = AdapterFactory._require_api_key(
                settings.GOOGLE_API_KEY,
                env_var_name="GOOGLE_API_KEY",
                provider=normalised_provider,
                target_model=normalised_model,
            )
            return GeminiAdapter(api_key=api_key, model=normalised_model)

        supported = ", ".join(_SUPPORTED_PROVIDERS)
        raise LLMAdapterError(
            f"Unsupported provider '{provider}'. Supported providers: {supported}."
        )

    @staticmethod
    def _require_api_key(
        api_key: str | None,
        *,
        env_var_name: str,
        provider: str,
        target_model: str,
    ) -> str:
        normalised_key = api_key.strip() if api_key else ""
        if not normalised_key:
            raise LLMAdapterError(
                f"{env_var_name} is required to use provider '{provider}' with "
                f"model '{target_model}'."
            )
        return normalised_key
