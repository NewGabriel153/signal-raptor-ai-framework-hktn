from __future__ import annotations

import asyncio
import json
import logging
import re
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
    build_tool_name_mappings,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_RETRIES: int = 3
_BASE_RETRY_DELAY: float = 1.0  # seconds; doubles each attempt
_MAX_FUNCTION_NAME_LENGTH: int = 128
_INVALID_FUNCTION_NAME_CHARS_RE = re.compile(r"[^A-Za-z0-9_.:-]")


# ---------------------------------------------------------------------------
# Internal helpers – message / tool conversion
# ---------------------------------------------------------------------------

def _build_tool_name_mappings(
    tools: list[dict[str, Any]] | None,
) -> tuple[dict[str, str], dict[str, str]]:
    return build_tool_name_mappings(
        tools,
        invalid_chars_re=_INVALID_FUNCTION_NAME_CHARS_RE,
        max_length=_MAX_FUNCTION_NAME_LENGTH,
        require_identifier_start=True,
    )


def _build_function_declarations(
    tools: list[dict[str, Any]],
    original_to_provider: dict[str, str],
) -> list[types.FunctionDeclaration]:
    declarations: list[types.FunctionDeclaration] = []
    for tool in tools:
        declarations.append(
            types.FunctionDeclaration(
                name=original_to_provider.get(tool["name"], tool["name"]),
                description=tool.get("description", ""),
                parameters_json_schema=tool.get("parameters"),
            )
        )
    return declarations


def _convert_messages(
    messages: list[dict[str, Any]],
    original_to_provider: dict[str, str],
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
                tool_name = original_to_provider.get(tc["name"], tc["name"])
                parts.append(
                    types.Part.from_function_call(
                        name=tool_name,
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
                            name=original_to_provider.get(
                                msg.get("name", "unknown"),
                                msg.get("name", "unknown"),
                            ),
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
    segments: list[str] = []
    for part in parts:
        try:
            text = part.text
        except (AttributeError, ValueError):
            continue
        if text:
            segments.append(text)
    return "".join(segments) if segments else None


def _to_plain_python(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _to_plain_python(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_plain_python(item) for item in value]
    if hasattr(value, "items"):
        try:
            return {str(key): _to_plain_python(item) for key, item in value.items()}
        except Exception:
            pass
    if hasattr(value, "model_dump"):
        try:
            return _to_plain_python(value.model_dump())
        except Exception:
            pass
    if hasattr(value, "to_dict"):
        try:
            return _to_plain_python(value.to_dict())
        except Exception:
            pass
    return value


def _args_to_dict(raw_args: Any) -> dict[str, Any]:
    plain_args = _to_plain_python(raw_args)
    if isinstance(plain_args, dict):
        return plain_args
    return {}


def _extract_tool_calls(parts: list[Any]) -> list[ToolCallRequest]:
    return _extract_tool_calls_with_mapping(parts, {})


def _extract_tool_calls_with_mapping(
    parts: list[Any],
    provider_to_original: dict[str, str],
) -> list[ToolCallRequest]:
    calls: list[ToolCallRequest] = []
    for part in parts:
        try:
            fc = getattr(part, "function_call", None)
        except (AttributeError, ValueError):
            continue
        if fc is None:
            continue
        raw_name = getattr(fc, "name", None)
        name = provider_to_original.get(raw_name, raw_name)
        if not name:
            continue
        calls.append(
            ToolCallRequest(
                id=getattr(fc, "id", None) or f"call_{uuid.uuid4().hex[:12]}",
                name=name,
                arguments=_args_to_dict(getattr(fc, "args", None)),
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
    if code == 404:
        return LLMAdapterError(
            "Gemini model not found or unsupported for generateContent. "
            f"Provider response: {msg}. "
            "Use a supported model ID such as 'gemini-2.5-flash', 'gemini-2.5-pro', "
            "'gemini-3-flash-preview', or 'gemini-3.1-flash-lite-preview'."
        )
    if code == 429:
        return LLMRateLimitError(f"Gemini rate limit exceeded: {msg}")
    return LLMAdapterError(f"Gemini client error ({code}): {msg}")


def _classify_terminal_retry_error(exc: Exception, retries: int) -> LLMAdapterError:
    if isinstance(exc, genai_errors.ClientError):
        classified = _classify_client_error(exc)
        if isinstance(classified, LLMRateLimitError):
            return LLMRateLimitError(
                f"{classified} after {retries} retries",
                retry_after=classified.retry_after,
            )
        return classified
    if isinstance(exc, genai_errors.ServerError):
        return LLMConnectionError(f"Gemini server error after {retries} retries: {exc}")
    return LLMAdapterError(f"Gemini request failed after {retries} retries: {exc}")


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
        original_to_provider, provider_to_original = _build_tool_name_mappings(tools)
        system_instruction, contents = _convert_messages(messages, original_to_provider)
        config = self._build_config(
            system_instruction,
            tools,
            temperature,
            max_tokens,
            original_to_provider,
        )

        response = await self._call_with_retry(contents, config)

        try:
            feedback = getattr(response, "prompt_feedback", None)
            if feedback and getattr(feedback, "block_reason", None):
                raise LLMContentFilterError(f"Prompt blocked by safety filter: {feedback}")

            candidates = getattr(response, "candidates", None) or []
            if not candidates:
                logger.warning("Gemini returned no candidates: %s", response)
                return LLMResponse(model=self._model, finish_reason="error")

            candidate = candidates[0]
            finish_reason = _normalise_finish_reason(candidate)
            if finish_reason == "content_filter":
                raise LLMContentFilterError(
                    "Response blocked by safety filter: "
                    f"{getattr(candidate, 'safety_ratings', None)}"
                )

            content = getattr(candidate, "content", None)
            parts = getattr(content, "parts", None) or []
            usage = getattr(response, "usage_metadata", None)

            return LLMResponse(
                content=_extract_text(parts),
                tool_calls=_extract_tool_calls_with_mapping(parts, provider_to_original),
                prompt_tokens=getattr(usage, "prompt_token_count", 0) or 0,
                completion_tokens=getattr(usage, "candidates_token_count", 0) or 0,
                model=self._model,
                finish_reason=finish_reason,
            )
        except LLMAdapterError:
            raise
        except Exception as exc:
            raise LLMAdapterError(f"Failed to parse Gemini response: {exc}") from exc

    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncGenerator[LLMStreamChunk, None]:
        original_to_provider, provider_to_original = _build_tool_name_mappings(tools)
        system_instruction, contents = _convert_messages(messages, original_to_provider)
        config = self._build_config(
            system_instruction,
            tools,
            temperature,
            max_tokens,
            original_to_provider,
        )

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
                    tool_calls=_extract_tool_calls_with_mapping(parts, provider_to_original),
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
        original_to_provider: dict[str, str] | None = None,
    ) -> types.GenerateContentConfig:
        kwargs: dict[str, Any] = {}
        if system_instruction:
            kwargs["system_instruction"] = system_instruction
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_output_tokens"] = max_tokens
        if tools:
            tool_name_mapping = original_to_provider or {}
            kwargs["tools"] = [
                types.Tool(
                    function_declarations=_build_function_declarations(tools, tool_name_mapping)
                )
            ]
            kwargs["tool_config"] = types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(mode="AUTO")
            )
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
                    last_exc = exc
                    if attempt == _MAX_RETRIES - 1:
                        raise _classify_terminal_retry_error(exc, _MAX_RETRIES) from exc
                    delay = _BASE_RETRY_DELAY * (2 ** attempt)
                    logger.warning(
                        "Gemini rate-limit hit (attempt %d/%d), retrying in %.1fs",
                        attempt + 1,
                        _MAX_RETRIES,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                raise _classify_client_error(exc) from exc
            except genai_errors.ServerError as exc:
                last_exc = exc
                if attempt == _MAX_RETRIES - 1:
                    raise _classify_terminal_retry_error(exc, _MAX_RETRIES) from exc
                delay = _BASE_RETRY_DELAY * (2 ** attempt)
                logger.warning(
                    "Gemini server error (attempt %d/%d), retrying in %.1fs: %s",
                    attempt + 1,
                    _MAX_RETRIES,
                    delay,
                    exc,
                )
                await asyncio.sleep(delay)
            except LLMAdapterError:
                raise
            except Exception as exc:
                raise LLMAdapterError(f"Unexpected error calling Gemini: {exc}") from exc

        if last_exc is not None:
            raise _classify_terminal_retry_error(last_exc, _MAX_RETRIES) from last_exc
        raise LLMAdapterError("Gemini request failed without a provider error.")
