from __future__ import annotations

import abc
from collections.abc import AsyncGenerator
from typing import Any

from pydantic import BaseModel, Field


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
