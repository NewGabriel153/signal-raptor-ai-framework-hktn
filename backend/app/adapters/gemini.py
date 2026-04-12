from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncGenerator
from typing import Any

from google import genai
from google.genai import errors as genai_errors, types

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

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_RETRIES: int = 3
_BASE_RETRY_DELAY: float = 1.0  # seconds; doubles each attempt

_JSON_SCHEMA_TYPE_TO_GEMINI: dict[str, str] = {
    "string": "STRING",
    "number": "NUMBER",
    "integer": "INTEGER",
    "boolean": "BOOLEAN",
    "array": "ARRAY",
    "object": "OBJECT",
}


# ---------------------------------------------------------------------------
# Internal helpers – message / tool conversion
# ---------------------------------------------------------------------------

def _upcase_schema_types(schema: dict[str, Any]) -> dict[str, Any]:
    """Recursively convert lowercase JSON-Schema ``type`` values to Gemini's
    uppercase enum strings (``STRING``, ``OBJECT``, …)."""
    out: dict[str, Any] = {}
    for key, value in schema.items():
        if key == "type" and isinstance(value, str):
            out[key] = _JSON_SCHEMA_TYPE_TO_GEMINI.get(value.lower(), value.upper())
        elif isinstance(value, dict):
            out[key] = _upcase_schema_types(value)
        elif isinstance(value, list):
            out[key] = [
                _upcase_schema_types(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            out[key] = value
    return out


def _build_function_declarations(
    tools: list[dict[str, Any]],
) -> list[types.FunctionDeclaration]:
    declarations: list[types.FunctionDeclaration] = []
    for tool in tools:
        params = tool.get("parameters")
        if params:
            params = _upcase_schema_types(params)
        declarations.append(
            types.FunctionDeclaration(
                name=tool["name"],
                description=tool.get("description", ""),
                parameters=params,
            )
        )
    return declarations


def _convert_messages(
    messages: list[dict[str, Any]],
) -> tuple[str | None, list[types.Content]]:
    """Split a system instruction out of the message list and convert the
    remaining messages to Gemini ``Content`` objects."""
    system_instruction: str | None = None
    contents: list[types.Content] = []

    for msg in messages:
        role = msg.get("role", "")

        if role == "system":
            system_instruction = msg.get("content", "")
            continue

        if role == "user":
            contents.append(
                types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=msg.get("content", ""))],
                )
            )

        elif role == "assistant":
            parts: list[types.Part] = []
            text = msg.get("content")
            if text:
                parts.append(types.Part.from_text(text=text))
            for tc in msg.get("tool_calls", []):
                parts.append(
                    types.Part.from_function_call(
                        name=tc["name"],
                        args=tc.get("arguments", {}),
                    )
                )
            if parts:
                contents.append(types.Content(role="model", parts=parts))

        elif role == "tool":
            raw = msg.get("content", "")
            try:
                response_data = json.loads(raw) if isinstance(raw, str) else raw
            except (json.JSONDecodeError, TypeError):
                response_data = {"result": raw}

            contents.append(
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_function_response(
                            name=msg.get("name", "unknown"),
                            response=response_data,
                        )
                    ],
                )
            )

    return system_instruction, contents


# ---------------------------------------------------------------------------
# Internal helpers – response normalisation
# ---------------------------------------------------------------------------

def _extract_text(parts: list[Any]) -> str | None:
    segments = [p.text for p in parts if getattr(p, "text", None)]
    return "".join(segments) if segments else None


def _extract_tool_calls(parts: list[Any]) -> list[ToolCallRequest]:
    calls: list[ToolCallRequest] = []
    for part in parts:
        fc = getattr(part, "function_call", None)
        if fc is None:
            continue
        calls.append(
            ToolCallRequest(
                id=f"call_{uuid.uuid4().hex[:12]}",
                name=fc.name,
                arguments=dict(fc.args) if fc.args else {},
            )
        )
    return calls


def _normalise_finish_reason(candidate: Any) -> str:
    raw = getattr(candidate, "finish_reason", None)
    if raw is None:
        return ""
    raw_str = str(raw).lower()
    if "stop" in raw_str:
        return "stop"
    if "tool" in raw_str or "function" in raw_str:
        return "tool_calls"
    if "safety" in raw_str:
        return "content_filter"
    if "length" in raw_str or "max_tokens" in raw_str:
        return "max_tokens"
    return raw_str


# ---------------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------------

def _classify_client_error(exc: genai_errors.ClientError) -> LLMAdapterError:
    code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    msg = str(exc)
    if code in (401, 403):
        return LLMAuthenticationError(f"Gemini authentication failed: {msg}")
    if code == 429:
        return LLMRateLimitError(f"Gemini rate limit exceeded: {msg}")
    return LLMAdapterError(f"Gemini client error ({code}): {msg}")


# ---------------------------------------------------------------------------
# Public adapter
# ---------------------------------------------------------------------------

class GeminiAdapter(BaseLLMAdapter):
    """Adapter for Google Gemini models via the ``google-genai`` SDK.

    All responses are normalised into the framework-standard
    :class:`LLMResponse` / :class:`LLMStreamChunk` models so the rest of the
    application never sees Gemini-specific types.
    """

    def __init__(self, *, api_key: str, model: str = "gemini-1.5-flash") -> None:
        if not api_key:
            raise LLMAuthenticationError("GOOGLE_API_KEY is required for GeminiAdapter.")
        self._model = model
        self._client = genai.Client(api_key=api_key)

    # -- public interface ---------------------------------------------------

    async def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        system_instruction, contents = _convert_messages(messages)
        config = self._build_config(system_instruction, tools, temperature, max_tokens)

        response = await self._call_with_retry(contents, config)

        candidate = response.candidates[0] if response.candidates else None
        if candidate is None:
            feedback = getattr(response, "prompt_feedback", None)
            if feedback:
                raise LLMContentFilterError(f"Prompt blocked by safety filter: {feedback}")
            return LLMResponse(model=self._model, finish_reason="error")

        parts = candidate.content.parts if candidate.content else []
        usage = response.usage_metadata

        return LLMResponse(
            content=_extract_text(parts),
            tool_calls=_extract_tool_calls(parts),
            prompt_tokens=getattr(usage, "prompt_token_count", 0) or 0,
            completion_tokens=getattr(usage, "candidates_token_count", 0) or 0,
            model=self._model,
            finish_reason=_normalise_finish_reason(candidate),
        )

    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncGenerator[LLMStreamChunk, None]:
        system_instruction, contents = _convert_messages(messages)
        config = self._build_config(system_instruction, tools, temperature, max_tokens)

        try:
            async for chunk in self._client.aio.models.generate_content_stream(
                model=self._model,
                contents=contents,
                config=config,
            ):
                candidate = chunk.candidates[0] if chunk.candidates else None
                if candidate is None:
                    continue
                parts = candidate.content.parts if candidate.content else []
                usage = chunk.usage_metadata
                yield LLMStreamChunk(
                    content=_extract_text(parts),
                    tool_calls=_extract_tool_calls(parts),
                    prompt_tokens=getattr(usage, "prompt_token_count", 0) or 0,
                    completion_tokens=getattr(usage, "candidates_token_count", 0) or 0,
                    finish_reason=_normalise_finish_reason(candidate),
                )
        except genai_errors.ClientError as exc:
            raise _classify_client_error(exc) from exc
        except genai_errors.ServerError as exc:
            raise LLMConnectionError(f"Gemini server error: {exc}") from exc
        except LLMAdapterError:
            raise
        except Exception as exc:
            raise LLMAdapterError(f"Unexpected error during Gemini stream: {exc}") from exc

    # -- internals ----------------------------------------------------------

    @staticmethod
    def _build_config(
        system_instruction: str | None,
        tools: list[dict[str, Any]] | None,
        temperature: float | None,
        max_tokens: int | None,
    ) -> types.GenerateContentConfig:
        kwargs: dict[str, Any] = {}
        if system_instruction:
            kwargs["system_instruction"] = system_instruction
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_output_tokens"] = max_tokens
        if tools:
            kwargs["tools"] = [
                types.Tool(function_declarations=_build_function_declarations(tools))
            ]
        return types.GenerateContentConfig(**kwargs)

    async def _call_with_retry(
        self,
        contents: list[types.Content],
        config: types.GenerateContentConfig,
    ) -> Any:
        last_exc: Exception | None = None

        for attempt in range(_MAX_RETRIES):
            try:
                return await self._client.aio.models.generate_content(
                    model=self._model,
                    contents=contents,
                    config=config,
                )
            except genai_errors.ClientError as exc:
                code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
                if code == 429:
                    delay = _BASE_RETRY_DELAY * (2 ** attempt)
                    logger.warning(
                        "Gemini rate-limit hit (attempt %d/%d), retrying in %.1fs",
                        attempt + 1,
                        _MAX_RETRIES,
                        delay,
                    )
                    last_exc = exc
                    await asyncio.sleep(delay)
                    continue
                raise _classify_client_error(exc) from exc
            except genai_errors.ServerError as exc:
                delay = _BASE_RETRY_DELAY * (2 ** attempt)
                logger.warning(
                    "Gemini server error (attempt %d/%d), retrying in %.1fs: %s",
                    attempt + 1,
                    _MAX_RETRIES,
                    delay,
                    exc,
                )
                last_exc = exc
                await asyncio.sleep(delay)
            except LLMAdapterError:
                raise
            except Exception as exc:
                raise LLMAdapterError(f"Unexpected error calling Gemini: {exc}") from exc

        raise LLMRateLimitError(
            f"Gemini rate limit exceeded after {_MAX_RETRIES} retries",
        ) from last_exc
