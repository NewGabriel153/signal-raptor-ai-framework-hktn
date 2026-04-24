from __future__ import annotations

import abc
import hashlib
import re
from collections.abc import AsyncGenerator
from typing import Any

from pydantic import BaseModel, Field


def sanitise_tool_name(
    name: str,
    *,
    invalid_chars_re: re.Pattern[str],
    max_length: int,
    require_identifier_start: bool = False,
) -> str:
    """Convert a framework tool name into a provider-safe function name."""

    candidate = invalid_chars_re.sub("_", (name or "").strip()) or "tool"
    if require_identifier_start and not (candidate[0].isalpha() or candidate[0] == "_"):
        candidate = f"_{candidate}"
    return candidate[:max_length]


def build_tool_name_mappings(
    tools: list[dict[str, Any]] | None,
    *,
    invalid_chars_re: re.Pattern[str],
    max_length: int,
    require_identifier_start: bool = False,
) -> tuple[dict[str, str], dict[str, str]]:
    """Map original framework tool names to provider-safe names and back."""

    original_to_provider: dict[str, str] = {}
    provider_to_original: dict[str, str] = {}
    used_provider_names: set[str] = set()

    for tool in tools or []:
        original_name = str(tool["name"])
        provider_name = sanitise_tool_name(
            original_name,
            invalid_chars_re=invalid_chars_re,
            max_length=max_length,
            require_identifier_start=require_identifier_start,
        )

        if provider_name != original_name:
            suffix = hashlib.sha1(original_name.encode("utf-8")).hexdigest()[:8]
            base_length = max_length - len(suffix) - 1
            provider_name = f"{provider_name[:base_length]}_{suffix}"

        collision_index = 1
        while provider_name in used_provider_names:
            suffix_source = f"{original_name}:{collision_index}"
            suffix = hashlib.sha1(suffix_source.encode("utf-8")).hexdigest()[:8]
            base_length = max_length - len(suffix) - 1
            provider_name = f"{provider_name[:base_length]}_{suffix}"
            collision_index += 1

        used_provider_names.add(provider_name)
        original_to_provider[original_name] = provider_name
        provider_to_original[provider_name] = original_name

    return original_to_provider, provider_to_original


# ---------------------------------------------------------------------------
# Standardized response models — every adapter normalizes into these
# ---------------------------------------------------------------------------

class ToolCallRequest(BaseModel):
    """A single tool/function call requested by the LLM."""

    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class LLMResponse(BaseModel):
    """Normalized non-streaming response from any LLM provider."""

    content: str | None = None
    tool_calls: list[ToolCallRequest] = Field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model: str = ""
    finish_reason: str = ""


class LLMStreamChunk(BaseModel):
    """A single chunk emitted during streaming."""

    content: str | None = None
    tool_calls: list[ToolCallRequest] = Field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    finish_reason: str = ""


# ---------------------------------------------------------------------------
# Adapter exceptions
# ---------------------------------------------------------------------------

class LLMAdapterError(Exception):
    """Base exception for all adapter errors."""


class LLMAuthenticationError(LLMAdapterError):
    """API key is missing or rejected by the provider."""


class LLMRateLimitError(LLMAdapterError):
    """Provider returned HTTP 429 or equivalent."""

    def __init__(self, message: str = "Rate limit exceeded", retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class LLMContentFilterError(LLMAdapterError):
    """Response was blocked by the provider's safety / content filter."""


class LLMConnectionError(LLMAdapterError):
    """Network or connectivity failure when reaching the provider."""


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class BaseLLMAdapter(abc.ABC):
    """Provider-agnostic interface every LLM adapter must implement.

    *messages* follows a simple dict format understood by the rest of the
    framework::

        {"role": "system",    "content": "..."}
        {"role": "user",      "content": "..."}
        {"role": "assistant", "content": "...", "tool_calls": [...]}
        {"role": "tool",      "name": "fn", "tool_call_id": "id", "content": "..."}

    *tools* is a list of JSON-Schema-style function declarations::

        {"name": "fn", "description": "...", "parameters": {<JSON Schema>}}
    """

    @abc.abstractmethod
    async def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        ...

    @abc.abstractmethod
    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncGenerator[LLMStreamChunk, None]:
        ...
        yield  # pragma: no cover – required for async-generator typing
