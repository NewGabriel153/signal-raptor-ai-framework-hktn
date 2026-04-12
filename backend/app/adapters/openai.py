from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

import openai

from app.adapters.base import (
    BaseLLMAdapter,
    LLMAdapterError,
    LLMAuthenticationError,
    LLMConnectionError,
    LLMContentFilterError,
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

def _build_oai_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Wrap framework tool dicts into the OpenAI function-calling format."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("parameters", {}),
            },
        }
        for t in tools
    ]


def _convert_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Translate framework messages into the OpenAI chat format."""
    out: list[dict[str, Any]] = []
    for msg in messages:
        role = msg.get("role", "user")

        if role == "tool":
            out.append({
                "role": "tool",
                "tool_call_id": msg.get("tool_call_id", ""),
                "content": msg.get("content", ""),
            })
        elif role == "assistant":
            entry: dict[str, Any] = {"role": "assistant"}
            if msg.get("content"):
                entry["content"] = msg["content"]
            if msg.get("tool_calls"):
                entry["tool_calls"] = [
                    {
                        "id": tc.get("id", ""),
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": (
                                json.dumps(tc["arguments"])
                                if isinstance(tc.get("arguments"), dict)
                                else tc.get("arguments", "")
                            ),
                        },
                    }
                    for tc in msg["tool_calls"]
                ]
            out.append(entry)
        else:
            out.append({"role": role, "content": msg.get("content", "")})

    return out


def _extract_tool_calls(choices_tc: Any) -> list[ToolCallRequest]:
    if not choices_tc:
        return []
    calls: list[ToolCallRequest] = []
    for tc in choices_tc:
        args_raw = tc.function.arguments
        try:
            args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
        except (json.JSONDecodeError, TypeError):
            args = {}
        calls.append(ToolCallRequest(id=tc.id, name=tc.function.name, arguments=args))
    return calls


def _normalise_finish_reason(raw: str | None) -> str:
    if raw is None:
        return ""
    if raw == "stop":
        return "stop"
    if raw == "tool_calls":
        return "tool_calls"
    if raw == "content_filter":
        return "content_filter"
    if raw in ("length", "max_tokens"):
        return "max_tokens"
    return raw


def _classify_error(exc: openai.APIError) -> LLMAdapterError:
    status = getattr(exc, "status_code", None)
    msg = str(exc)
    if isinstance(exc, openai.AuthenticationError):
        return LLMAuthenticationError(f"OpenAI authentication failed: {msg}")
    if isinstance(exc, openai.RateLimitError):
        return LLMRateLimitError(f"OpenAI rate limit exceeded: {msg}")
    if status and status >= 500:
        return LLMConnectionError(f"OpenAI server error ({status}): {msg}")
    return LLMAdapterError(f"OpenAI API error ({status}): {msg}")


# ---------------------------------------------------------------------------
# Public adapter
# ---------------------------------------------------------------------------

class OpenAIAdapter(BaseLLMAdapter):
    """Adapter for OpenAI chat models (GPT-4o, GPT-4o-mini, o1, etc.).

    All responses are normalised into the framework-standard
    :class:`LLMResponse` / :class:`LLMStreamChunk` models.
    """

    def __init__(self, *, api_key: str, model: str = "gpt-4o-mini") -> None:
        if not api_key:
            raise LLMAuthenticationError("OPENAI_API_KEY is required for OpenAIAdapter.")
        self._model = model
        self._client = openai.AsyncOpenAI(api_key=api_key)

    async def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": _convert_messages(messages),
        }
        if tools:
            kwargs["tools"] = _build_oai_tools(tools)
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        response = await self._call_with_retry(kwargs)

        choice = response.choices[0] if response.choices else None
        if choice is None:
            return LLMResponse(model=self._model, finish_reason="error")

        usage = response.usage
        return LLMResponse(
            content=choice.message.content,
            tool_calls=_extract_tool_calls(choice.message.tool_calls),
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            model=self._model,
            finish_reason=_normalise_finish_reason(choice.finish_reason),
        )

    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncGenerator[LLMStreamChunk, None]:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": _convert_messages(messages),
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            kwargs["tools"] = _build_oai_tools(tools)
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        try:
            stream = await self._client.chat.completions.create(**kwargs)
            async for chunk in stream:
                choice = chunk.choices[0] if chunk.choices else None
                delta_content: str | None = None
                delta_tool_calls: list[ToolCallRequest] = []
                finish_reason = ""

                if choice:
                    delta = choice.delta
                    delta_content = getattr(delta, "content", None)
                    delta_tool_calls = _extract_tool_calls(getattr(delta, "tool_calls", None))
                    finish_reason = _normalise_finish_reason(choice.finish_reason)

                usage = chunk.usage
                yield LLMStreamChunk(
                    content=delta_content,
                    tool_calls=delta_tool_calls,
                    prompt_tokens=usage.prompt_tokens if usage else 0,
                    completion_tokens=usage.completion_tokens if usage else 0,
                    finish_reason=finish_reason,
                )
        except openai.APIError as exc:
            raise _classify_error(exc) from exc
        except LLMAdapterError:
            raise
        except Exception as exc:
            raise LLMAdapterError(f"Unexpected error during OpenAI stream: {exc}") from exc

    async def _call_with_retry(self, kwargs: dict[str, Any]) -> Any:
        last_exc: Exception | None = None

        for attempt in range(_MAX_RETRIES):
            try:
                return await self._client.chat.completions.create(**kwargs)
            except openai.RateLimitError as exc:
                delay = _BASE_RETRY_DELAY * (2 ** attempt)
                logger.warning(
                    "OpenAI rate-limit hit (attempt %d/%d), retrying in %.1fs",
                    attempt + 1, _MAX_RETRIES, delay,
                )
                last_exc = exc
                await asyncio.sleep(delay)
            except openai.APIStatusError as exc:
                if exc.status_code >= 500:
                    delay = _BASE_RETRY_DELAY * (2 ** attempt)
                    logger.warning(
                        "OpenAI server error %d (attempt %d/%d), retrying in %.1fs",
                        exc.status_code, attempt + 1, _MAX_RETRIES, delay,
                    )
                    last_exc = exc
                    await asyncio.sleep(delay)
                    continue
                raise _classify_error(exc) from exc
            except openai.APIError as exc:
                raise _classify_error(exc) from exc
            except LLMAdapterError:
                raise
            except Exception as exc:
                raise LLMAdapterError(f"Unexpected error calling OpenAI: {exc}") from exc

        raise LLMRateLimitError(
            f"OpenAI rate limit exceeded after {_MAX_RETRIES} retries",
        ) from last_exc
