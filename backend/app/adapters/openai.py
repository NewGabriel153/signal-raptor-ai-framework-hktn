from __future__ import annotations

import asyncio
import json
import logging
import re
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
    build_tool_name_mappings,
)

logger = logging.getLogger(__name__)

_MAX_RETRIES: int = 3
_BASE_RETRY_DELAY: float = 1.0
_MAX_TOOL_NAME_LENGTH: int = 64
_INVALID_TOOL_NAME_CHARS_RE = re.compile(r"[^A-Za-z0-9_-]")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_oai_tools(
    tools: list[dict[str, Any]],
    original_to_provider: dict[str, str],
) -> list[dict[str, Any]]:
    """Wrap framework tool dicts into the OpenAI function-calling format."""
    return [
        {
            "type": "function",
            "function": {
                "name": original_to_provider.get(t["name"], t["name"]),
                "description": t.get("description", ""),
                "parameters": t.get("parameters", {}),
            },
        }
        for t in tools
    ]


def _convert_messages(
    messages: list[dict[str, Any]],
    original_to_provider: dict[str, str],
) -> list[dict[str, Any]]:
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
                            "name": original_to_provider.get(tc["name"], tc["name"]),
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


def _extract_tool_calls(
    choices_tc: Any,
    provider_to_original: dict[str, str] | None = None,
) -> list[ToolCallRequest]:
    if not choices_tc:
        return []
    calls: list[ToolCallRequest] = []
    tool_name_mapping = provider_to_original or {}
    for tc in choices_tc:
        args_raw = tc.function.arguments
        try:
            args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
        except (json.JSONDecodeError, TypeError):
            args = {}
        raw_name = tc.function.name
        calls.append(
            ToolCallRequest(
                id=tc.id,
                name=tool_name_mapping.get(raw_name, raw_name),
                arguments=args,
            )
        )
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


def _extract_error_payload(exc: openai.APIError) -> dict[str, Any]:
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            return error

    response = getattr(exc, "response", None)
    if response is None:
        return {}

    try:
        payload = response.json()
    except Exception:
        return {}

    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            return error
    return {}


def _extract_retry_after(exc: openai.APIError) -> float | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers is None or not hasattr(headers, "get"):
        return None

    retry_after = headers.get("retry-after")
    if retry_after is None:
        return None

    try:
        return float(retry_after)
    except (TypeError, ValueError):
        return None


def _format_error_message(exc: openai.APIError) -> str:
    payload = _extract_error_payload(exc)
    message = payload.get("message")
    code = payload.get("code")
    error_type = payload.get("type")

    parts: list[str] = []
    if isinstance(message, str) and message.strip():
        parts.append(message.strip())
    else:
        parts.append(str(exc))

    if code:
        parts.append(f"code={code}")
    if error_type:
        parts.append(f"type={error_type}")
    return " | ".join(parts)


def _is_hard_quota_error(exc: openai.RateLimitError) -> bool:
    payload = _extract_error_payload(exc)
    code = str(payload.get("code") or "").lower()
    error_type = str(payload.get("type") or "").lower()
    message = str(payload.get("message") or exc).lower()

    hard_limit_codes = {
        "insufficient_quota",
        "billing_hard_limit_reached",
        "account_deactivated",
    }

    if code in hard_limit_codes or error_type in hard_limit_codes:
        return True

    if "please check your plan and billing details" in message:
        return True

    return "insufficient quota" in message or ("billing" in message and "quota" in message)


def _classify_error(exc: openai.APIError) -> LLMAdapterError:
    status = getattr(exc, "status_code", None)
    msg = _format_error_message(exc)
    if isinstance(exc, openai.AuthenticationError):
        return LLMAuthenticationError(f"OpenAI authentication failed: {msg}")
    if isinstance(exc, openai.RateLimitError):
        if _is_hard_quota_error(exc):
            return LLMAdapterError(f"OpenAI quota or billing issue: {msg}")
        return LLMRateLimitError(
            f"OpenAI rate limit exceeded: {msg}",
            retry_after=_extract_retry_after(exc),
        )
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
        original_to_provider, provider_to_original = build_tool_name_mappings(
            tools,
            invalid_chars_re=_INVALID_TOOL_NAME_CHARS_RE,
            max_length=_MAX_TOOL_NAME_LENGTH,
        )
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": _convert_messages(messages, original_to_provider),
        }
        if tools:
            kwargs["tools"] = _build_oai_tools(tools, original_to_provider)
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
            tool_calls=_extract_tool_calls(choice.message.tool_calls, provider_to_original),
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
        original_to_provider, provider_to_original = build_tool_name_mappings(
            tools,
            invalid_chars_re=_INVALID_TOOL_NAME_CHARS_RE,
            max_length=_MAX_TOOL_NAME_LENGTH,
        )
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": _convert_messages(messages, original_to_provider),
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            kwargs["tools"] = _build_oai_tools(tools, original_to_provider)
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
                    delta_tool_calls = _extract_tool_calls(
                        getattr(delta, "tool_calls", None),
                        provider_to_original,
                    )
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
                if _is_hard_quota_error(exc):
                    raise _classify_error(exc) from exc

                retry_after = _extract_retry_after(exc)
                delay = retry_after if retry_after is not None else _BASE_RETRY_DELAY * (2 ** attempt)
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

        if isinstance(last_exc, openai.APIError):
            classified = _classify_error(last_exc)
            if isinstance(classified, LLMRateLimitError):
                raise LLMRateLimitError(
                    f"{classified} after {_MAX_RETRIES} retries",
                    retry_after=classified.retry_after,
                ) from last_exc
            if isinstance(classified, LLMConnectionError):
                raise LLMConnectionError(f"{classified} after {_MAX_RETRIES} retries") from last_exc
            raise classified from last_exc

        raise LLMAdapterError(f"OpenAI request failed after {_MAX_RETRIES} retries") from last_exc
