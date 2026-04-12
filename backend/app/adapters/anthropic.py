from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

import anthropic

from app.adapters.base import (
    BaseLLMAdapter,
    LLMAdapterError,
    LLMAuthenticationError,
    LLMConnectionError,
    LLMRateLimitError,
    LLMResponse,
    LLMStreamChunk,
    ToolCallRequest,
)

logger = logging.getLogger(__name__)

_MAX_RETRIES: int = 3
_BASE_RETRY_DELAY: float = 1.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_anthropic_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Wrap framework tool dicts into the Anthropic tool format."""
    return [
        {
            "name": t["name"],
            "description": t.get("description", ""),
            "input_schema": t.get("parameters", {"type": "object", "properties": {}}),
        }
        for t in tools
    ]


def _convert_messages(
    messages: list[dict[str, Any]],
) -> tuple[str | None, list[dict[str, Any]]]:
    """Split out the system prompt and convert framework messages to
    the Anthropic format."""
    system: str | None = None
    out: list[dict[str, Any]] = []

    for msg in messages:
        role = msg.get("role", "user")

        if role == "system":
            system = msg.get("content", "")
            continue

        if role == "assistant":
            content_blocks: list[dict[str, Any]] = []
            text = msg.get("content")
            if text:
                content_blocks.append({"type": "text", "text": text})
            for tc in msg.get("tool_calls", []):
                content_blocks.append({
                    "type": "tool_use",
                    "id": tc.get("id", ""),
                    "name": tc["name"],
                    "input": tc.get("arguments", {}),
                })
            out.append({"role": "assistant", "content": content_blocks or text or ""})

        elif role == "tool":
            out.append({
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": msg.get("tool_call_id", ""),
                        "content": msg.get("content", ""),
                    }
                ],
            })

        else:
            out.append({"role": "user", "content": msg.get("content", "")})

    return system, out


def _extract_tool_calls(content_blocks: list[Any]) -> list[ToolCallRequest]:
    calls: list[ToolCallRequest] = []
    for block in content_blocks:
        if getattr(block, "type", None) == "tool_use":
            calls.append(
                ToolCallRequest(
                    id=block.id,
                    name=block.name,
                    arguments=block.input if isinstance(block.input, dict) else {},
                )
            )
    return calls


def _extract_text(content_blocks: list[Any]) -> str | None:
    segments = [
        block.text
        for block in content_blocks
        if getattr(block, "type", None) == "text" and getattr(block, "text", None)
    ]
    return "".join(segments) if segments else None


def _normalise_stop_reason(raw: str | None) -> str:
    if raw is None:
        return ""
    if raw == "end_turn":
        return "stop"
    if raw == "tool_use":
        return "tool_calls"
    if raw == "max_tokens":
        return "max_tokens"
    return raw


def _classify_error(exc: anthropic.APIError) -> LLMAdapterError:
    status = getattr(exc, "status_code", None)
    msg = str(exc)
    if isinstance(exc, anthropic.AuthenticationError):
        return LLMAuthenticationError(f"Anthropic authentication failed: {msg}")
    if isinstance(exc, anthropic.RateLimitError):
        return LLMRateLimitError(f"Anthropic rate limit exceeded: {msg}")
    if isinstance(exc, anthropic.InternalServerError):
        return LLMConnectionError(f"Anthropic server error ({status}): {msg}")
    return LLMAdapterError(f"Anthropic API error ({status}): {msg}")


# ---------------------------------------------------------------------------
# Public adapter
# ---------------------------------------------------------------------------

class AnthropicAdapter(BaseLLMAdapter):
    """Adapter for Anthropic Claude models.

    All responses are normalised into the framework-standard
    :class:`LLMResponse` / :class:`LLMStreamChunk` models.
    """

    def __init__(self, *, api_key: str, model: str = "claude-sonnet-4-20250514") -> None:
        if not api_key:
            raise LLMAuthenticationError("ANTHROPIC_API_KEY is required for AnthropicAdapter.")
        self._model = model
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    async def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        system, converted = _convert_messages(messages)

        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": converted,
            "max_tokens": max_tokens or 4096,
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = _build_anthropic_tools(tools)
        if temperature is not None:
            kwargs["temperature"] = temperature

        response = await self._call_with_retry(kwargs)

        return LLMResponse(
            content=_extract_text(response.content),
            tool_calls=_extract_tool_calls(response.content),
            prompt_tokens=response.usage.input_tokens if response.usage else 0,
            completion_tokens=response.usage.output_tokens if response.usage else 0,
            model=self._model,
            finish_reason=_normalise_stop_reason(response.stop_reason),
        )

    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncGenerator[LLMStreamChunk, None]:
        system, converted = _convert_messages(messages)

        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": converted,
            "max_tokens": max_tokens or 4096,
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = _build_anthropic_tools(tools)
        if temperature is not None:
            kwargs["temperature"] = temperature

        try:
            async with self._client.messages.stream(**kwargs) as stream:
                # Accumulate tool-use blocks across deltas
                current_tool: dict[str, Any] | None = None
                input_tokens = 0
                output_tokens = 0

                async for event in stream:
                    if event.type == "message_start" and hasattr(event, "message"):
                        usage = getattr(event.message, "usage", None)
                        if usage:
                            input_tokens = getattr(usage, "input_tokens", 0)

                    elif event.type == "content_block_start":
                        block = event.content_block
                        if getattr(block, "type", None) == "tool_use":
                            current_tool = {
                                "id": block.id,
                                "name": block.name,
                                "arguments_json": "",
                            }

                    elif event.type == "content_block_delta":
                        delta = event.delta
                        if getattr(delta, "type", None) == "text_delta":
                            yield LLMStreamChunk(
                                content=delta.text,
                                prompt_tokens=input_tokens,
                                completion_tokens=output_tokens,
                            )
                        elif (
                            getattr(delta, "type", None) == "input_json_delta"
                            and current_tool is not None
                        ):
                            current_tool["arguments_json"] += delta.partial_json

                    elif event.type == "content_block_stop":
                        if current_tool is not None:
                            try:
                                args = json.loads(current_tool["arguments_json"])
                            except (json.JSONDecodeError, TypeError):
                                args = {}
                            yield LLMStreamChunk(
                                tool_calls=[
                                    ToolCallRequest(
                                        id=current_tool["id"],
                                        name=current_tool["name"],
                                        arguments=args,
                                    )
                                ],
                                prompt_tokens=input_tokens,
                                completion_tokens=output_tokens,
                            )
                            current_tool = None

                    elif event.type == "message_delta":
                        usage = getattr(event, "usage", None)
                        if usage:
                            output_tokens = getattr(usage, "output_tokens", 0)
                        stop_reason = getattr(event.delta, "stop_reason", None) if hasattr(event, "delta") else None
                        if stop_reason:
                            yield LLMStreamChunk(
                                finish_reason=_normalise_stop_reason(stop_reason),
                                prompt_tokens=input_tokens,
                                completion_tokens=output_tokens,
                            )
        except anthropic.APIError as exc:
            raise _classify_error(exc) from exc
        except LLMAdapterError:
            raise
        except Exception as exc:
            raise LLMAdapterError(f"Unexpected error during Anthropic stream: {exc}") from exc

    async def _call_with_retry(self, kwargs: dict[str, Any]) -> Any:
        last_exc: Exception | None = None

        for attempt in range(_MAX_RETRIES):
            try:
                return await self._client.messages.create(**kwargs)
            except anthropic.RateLimitError as exc:
                delay = _BASE_RETRY_DELAY * (2 ** attempt)
                logger.warning(
                    "Anthropic rate-limit hit (attempt %d/%d), retrying in %.1fs",
                    attempt + 1, _MAX_RETRIES, delay,
                )
                last_exc = exc
                await asyncio.sleep(delay)
            except anthropic.InternalServerError as exc:
                delay = _BASE_RETRY_DELAY * (2 ** attempt)
                logger.warning(
                    "Anthropic server error (attempt %d/%d), retrying in %.1fs: %s",
                    attempt + 1, _MAX_RETRIES, delay, exc,
                )
                last_exc = exc
                await asyncio.sleep(delay)
            except anthropic.APIError as exc:
                raise _classify_error(exc) from exc
            except LLMAdapterError:
                raise
            except Exception as exc:
                raise LLMAdapterError(f"Unexpected error calling Anthropic: {exc}") from exc

        raise LLMRateLimitError(
            f"Anthropic rate limit exceeded after {_MAX_RETRIES} retries",
        ) from last_exc
