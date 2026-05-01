from __future__ import annotations

from types import SimpleNamespace
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from google.genai import errors as genai_errors


BACKEND_DIR = Path(__file__).resolve().parent

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


_IMPORT_ERROR: ModuleNotFoundError | None = None

try:
    from app.adapters.gemini import GeminiAdapter, _build_tool_name_mappings
    from app.adapters.base import LLMConnectionError, LLMContentFilterError, LLMRateLimitError
except ModuleNotFoundError as exc:
    GeminiAdapter = None
    _IMPORT_ERROR = exc


@unittest.skipIf(
    GeminiAdapter is None,
    "Backend dependencies are not installed. "
    f"Run 'pip install -r backend/requirements.txt' first. ({_IMPORT_ERROR})",
)
class GeminiAdapterBuildConfigTests(unittest.TestCase):
    maxDiff = None

    def test_build_config_uses_json_schema_tools_and_auto_function_calling(self) -> None:
        db_tool_schema = {
            "name": "calculator",
            "description": "Perform arithmetic operations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": ["add", "subtract", "multiply", "divide"],
                    },
                    "a": {"type": "number"},
                    "b": {"type": "number"},
                },
                "required": ["operation", "a", "b"],
            },
        }

        config = GeminiAdapter._build_config(
            system_instruction="You may use registered tools.",
            tools=[db_tool_schema],
            temperature=0.2,
            max_tokens=256,
        )

        self.assertEqual(config.system_instruction, "You may use registered tools.")
        self.assertEqual(config.temperature, 0.2)
        self.assertEqual(config.max_output_tokens, 256)
        self.assertIsNotNone(config.tools)
        self.assertEqual(len(config.tools), 1)

        declaration = config.tools[0].function_declarations[0]
        parameters_json_schema = getattr(declaration, "parameters_json_schema", None)

        self.assertEqual(declaration.name, "calculator")
        self.assertEqual(declaration.description, "Perform arithmetic operations.")
        self.assertIsNotNone(parameters_json_schema)
        self.assertEqual(parameters_json_schema, db_tool_schema["parameters"])
        self.assertEqual(parameters_json_schema["type"], "object")
        self.assertEqual(
            parameters_json_schema["properties"]["operation"]["type"],
            "string",
        )

        self.assertIsNotNone(config.tool_config)
        self.assertIsNotNone(config.tool_config.function_calling_config)
        self.assertIn(
            "AUTO",
            str(config.tool_config.function_calling_config.mode).upper(),
        )

    def test_build_config_sanitises_invalid_function_names_for_gemini(self) -> None:
        db_tool_schema = {
            "name": "123 bad tool!",
            "description": "Perform arithmetic operations.",
            "parameters": {
                "type": "object",
                "properties": {"value": {"type": "number"}},
                "required": ["value"],
            },
        }

        original_to_provider, _ = _build_tool_name_mappings([db_tool_schema])
        config = GeminiAdapter._build_config(
            system_instruction=None,
            tools=[db_tool_schema],
            temperature=None,
            max_tokens=None,
            original_to_provider=original_to_provider,
        )

        declaration = config.tools[0].function_declarations[0]
        self.assertNotEqual(declaration.name, db_tool_schema["name"])
        self.assertRegex(declaration.name, r"^[A-Za-z_][A-Za-z0-9_.:-]{0,127}$")


class _MappingLike:
    def __init__(self, data: dict[str, object]) -> None:
        self._data = data

    def items(self):
        return self._data.items()


class _FunctionCallPart:
    def __init__(self, *, name: str, args: dict[str, object], thought_signature: str | bytes | None = None) -> None:
        self.function_call = SimpleNamespace(name=name, args=_MappingLike(args))
        self.thought_signature = thought_signature

    @property
    def text(self) -> str:
        raise ValueError("function call parts do not expose text")


class _TextPart:
    def __init__(self, text: str) -> None:
        self._text = text

    @property
    def text(self) -> str:
        return self._text

    @property
    def function_call(self):
        return None


@unittest.skipIf(
    GeminiAdapter is None,
    "Backend dependencies are not installed. "
    f"Run 'pip install -r backend/requirements.txt' first. ({_IMPORT_ERROR})",
)
class GeminiAdapterResponseParsingTests(unittest.IsolatedAsyncioTestCase):
    async def test_generate_parses_function_call_parts_when_text_access_raises(self) -> None:
        response = SimpleNamespace(
            candidates=[
                SimpleNamespace(
                    content=SimpleNamespace(
                        parts=[
                            _FunctionCallPart(
                                name="calculator",
                                args={"operation": "add", "a": 2, "b": 3},
                            ),
                            _TextPart("computed"),
                        ]
                    ),
                    finish_reason="function_call",
                )
            ],
            usage_metadata=SimpleNamespace(prompt_token_count=11, candidates_token_count=7),
            prompt_feedback=None,
        )

        adapter = object.__new__(GeminiAdapter)
        adapter._model = "gemini-test"

        async def fake_call_with_retry(contents, config):
            return response

        adapter._call_with_retry = fake_call_with_retry

        llm_response = await adapter.generate(
            messages=[{"role": "user", "content": "what is 2 + 3?"}],
            tools=None,
        )

        self.assertEqual(llm_response.content, "computed")
        self.assertEqual(llm_response.finish_reason, "tool_calls")
        self.assertEqual(llm_response.prompt_tokens, 11)
        self.assertEqual(llm_response.completion_tokens, 7)
        self.assertEqual(len(llm_response.tool_calls), 1)
        self.assertEqual(llm_response.tool_calls[0].name, "calculator")
        self.assertEqual(
            llm_response.tool_calls[0].arguments,
            {"operation": "add", "a": 2, "b": 3},
        )

    async def test_generate_maps_sanitised_provider_tool_name_back_to_original(self) -> None:
        original_tool_name = "123 bad tool!"
        captured_provider_name: dict[str, str] = {}

        adapter = object.__new__(GeminiAdapter)
        adapter._model = "gemini-test"

        async def fake_call_with_retry(contents, config):
            provider_name = config.tools[0].function_declarations[0].name
            captured_provider_name["value"] = provider_name
            return SimpleNamespace(
                candidates=[
                    SimpleNamespace(
                        content=SimpleNamespace(
                            parts=[
                                _FunctionCallPart(
                                    name=provider_name,
                                    args={"operation": "multiply", "a": 123456, "b": 987654},
                                )
                            ]
                        ),
                        finish_reason="function_call",
                    )
                ],
                usage_metadata=SimpleNamespace(prompt_token_count=10, candidates_token_count=5),
                prompt_feedback=None,
            )

        adapter._call_with_retry = fake_call_with_retry

        llm_response = await adapter.generate(
            messages=[{"role": "user", "content": "use the tool"}],
            tools=[
                {
                    "name": original_tool_name,
                    "description": "Multiply numbers.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "operation": {"type": "string"},
                            "a": {"type": "number"},
                            "b": {"type": "number"},
                        },
                        "required": ["operation", "a", "b"],
                    },
                }
            ],
        )

        self.assertIn("value", captured_provider_name)
        self.assertRegex(captured_provider_name["value"], r"^[A-Za-z_][A-Za-z0-9_.:-]{0,127}$")
        self.assertEqual(len(llm_response.tool_calls), 1)
        self.assertEqual(llm_response.tool_calls[0].name, original_tool_name)
        self.assertEqual(
            llm_response.tool_calls[0].arguments,
            {"operation": "multiply", "a": 123456, "b": 987654},
        )

    async def test_generate_returns_error_response_when_candidates_are_empty(self) -> None:
        response = SimpleNamespace(candidates=[], usage_metadata=None, prompt_feedback=None)

        adapter = object.__new__(GeminiAdapter)
        adapter._model = "gemini-test"

        async def fake_call_with_retry(contents, config):
            return response

        adapter._call_with_retry = fake_call_with_retry

        llm_response = await adapter.generate(
            messages=[{"role": "user", "content": "hello"}],
            tools=None,
        )

        self.assertIsNone(llm_response.content)
        self.assertEqual(llm_response.tool_calls, [])
        self.assertEqual(llm_response.finish_reason, "error")

    async def test_generate_raises_content_filter_error_for_prompt_block(self) -> None:
        response = SimpleNamespace(
            candidates=[],
            usage_metadata=None,
            prompt_feedback=SimpleNamespace(block_reason="SAFETY"),
        )

        adapter = object.__new__(GeminiAdapter)
        adapter._model = "gemini-test"

        async def fake_call_with_retry(contents, config):
            return response

        adapter._call_with_retry = fake_call_with_retry

        with self.assertRaises(LLMContentFilterError):
            await adapter.generate(
                messages=[{"role": "user", "content": "blocked prompt"}],
                tools=None,
            )


class _FakeClientRateLimitError(genai_errors.ClientError):
    def __init__(self, message: str, *, status_code: int = 429) -> None:
        Exception.__init__(self, message)
        self.status_code = status_code


class _FakeServerError(genai_errors.ServerError):
    def __init__(self, message: str) -> None:
        Exception.__init__(self, message)


@unittest.skipIf(
    GeminiAdapter is None,
    "Backend dependencies are not installed. "
    f"Run 'pip install -r backend/requirements.txt' first. ({_IMPORT_ERROR})",
)
class GeminiAdapterThoughtSignatureTests(unittest.IsolatedAsyncioTestCase):
    """Gemini 3 requires thought_signature on function call parts."""

    async def test_generate_captures_thought_signature_bytes_as_base64(self) -> None:
        """The SDK returns thought_signature as raw bytes; the adapter must
        base64-encode it into a string for safe JSON round-tripping."""
        import base64

        raw_bytes = b'\x12\x8d\x03\n\x8a\x03test-signature-bytes'
        response = SimpleNamespace(
            candidates=[
                SimpleNamespace(
                    content=SimpleNamespace(
                        parts=[
                            _FunctionCallPart(
                                name="calculator",
                                args={"a": 1, "b": 2},
                                thought_signature=raw_bytes,
                            ),
                        ]
                    ),
                    finish_reason="function_call",
                )
            ],
            usage_metadata=SimpleNamespace(prompt_token_count=5, candidates_token_count=3),
            prompt_feedback=None,
        )

        adapter = object.__new__(GeminiAdapter)
        adapter._model = "gemini-3-flash-preview"

        async def fake_call_with_retry(contents, config):
            return response

        adapter._call_with_retry = fake_call_with_retry

        llm_response = await adapter.generate(
            messages=[{"role": "user", "content": "multiply"}],
            tools=None,
        )

        self.assertEqual(len(llm_response.tool_calls), 1)
        sig = llm_response.tool_calls[0].thought_signature
        self.assertIsInstance(sig, str)
        # Decoding should recover the original bytes
        self.assertEqual(base64.b64decode(sig), raw_bytes)

    async def test_generate_handles_missing_thought_signature(self) -> None:
        """Gemini 2.5 models won't have thought_signature; field should be None."""
        response = SimpleNamespace(
            candidates=[
                SimpleNamespace(
                    content=SimpleNamespace(
                        parts=[
                            _FunctionCallPart(
                                name="calculator",
                                args={"a": 1, "b": 2},
                            ),
                        ]
                    ),
                    finish_reason="function_call",
                )
            ],
            usage_metadata=SimpleNamespace(prompt_token_count=5, candidates_token_count=3),
            prompt_feedback=None,
        )

        adapter = object.__new__(GeminiAdapter)
        adapter._model = "gemini-2.5-flash"

        async def fake_call_with_retry(contents, config):
            return response

        adapter._call_with_retry = fake_call_with_retry

        llm_response = await adapter.generate(
            messages=[{"role": "user", "content": "multiply"}],
            tools=None,
        )

        self.assertEqual(len(llm_response.tool_calls), 1)
        self.assertIsNone(llm_response.tool_calls[0].thought_signature)

    def test_convert_messages_replays_thought_signature_as_bytes(self) -> None:
        """When assistant messages carry a base64-encoded thought_signature,
        _convert_messages must decode it back to bytes on the Part."""
        import base64
        from app.adapters.gemini import _convert_messages

        raw_bytes = b'\x12\x8d\x03\n\x8a\x03test-round-trip'
        b64_sig = base64.b64encode(raw_bytes).decode("ascii")

        messages = [
            {"role": "user", "content": "multiply 2 and 3"},
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "name": "calculator",
                        "arguments": {"a": 2, "b": 3},
                        "thought_signature": b64_sig,
                    }
                ],
            },
            {
                "role": "tool",
                "name": "calculator",
                "tool_call_id": "call_1",
                "content": '{"result": 6}',
            },
        ]

        _, contents = _convert_messages(messages, {})

        # contents[0] = user, contents[1] = model (assistant), contents[2] = tool
        self.assertEqual(len(contents), 3)
        model_content = contents[1]
        self.assertEqual(model_content.role, "model")
        fc_part = model_content.parts[0]

        # The part should have thought_signature set as bytes
        sig = getattr(fc_part, "thought_signature", None)
        self.assertEqual(sig, raw_bytes)

    def test_convert_messages_omits_signature_when_absent(self) -> None:
        """When no thought_signature is present (Gemini 2.5), parts should
        not have the field set to a truthy value."""
        from app.adapters.gemini import _convert_messages

        messages = [
            {"role": "user", "content": "hello"},
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "name": "calculator",
                        "arguments": {"a": 1, "b": 1},
                    }
                ],
            },
        ]

        _, contents = _convert_messages(messages, {})
        model_content = contents[1]
        fc_part = model_content.parts[0]

        sig = getattr(fc_part, "thought_signature", None)
        self.assertFalse(sig)  # None or empty/falsy

    def test_thought_signature_included_in_model_dump(self) -> None:
        """ToolCallRequest.model_dump() must include thought_signature so the
        ReAct orchestrator carries it through conversation history."""
        from app.adapters.base import ToolCallRequest

        tc = ToolCallRequest(
            id="call_1",
            name="calculator",
            arguments={"a": 1},
            thought_signature="sig_test",
        )
        dumped = tc.model_dump()
        self.assertEqual(dumped["thought_signature"], "sig_test")

        tc_no_sig = ToolCallRequest(id="call_2", name="calc", arguments={})
        dumped_no_sig = tc_no_sig.model_dump()
        self.assertIsNone(dumped_no_sig["thought_signature"])


@unittest.skipIf(
    GeminiAdapter is None,
    "Backend dependencies are not installed. "
    f"Run 'pip install -r backend/requirements.txt' first. ({_IMPORT_ERROR})",
)
class GeminiAdapterRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_call_with_retry_preserves_rate_limit_error_details(self) -> None:
        adapter = object.__new__(GeminiAdapter)
        adapter._model = "gemini-test"

        async def always_rate_limit(*, model, contents, config):
            raise _FakeClientRateLimitError("quota exhausted")

        adapter._client = SimpleNamespace(
            aio=SimpleNamespace(models=SimpleNamespace(generate_content=always_rate_limit))
        )

        with patch("app.adapters.gemini.asyncio.sleep", new=self._no_sleep):
            with self.assertRaises(LLMRateLimitError) as ctx:
                await adapter._call_with_retry(contents=[], config=SimpleNamespace())

        self.assertIn("quota exhausted", str(ctx.exception))
        self.assertIn("after 3 retries", str(ctx.exception))

    async def test_call_with_retry_preserves_server_error_type(self) -> None:
        adapter = object.__new__(GeminiAdapter)
        adapter._model = "gemini-test"

        async def always_server_error(*, model, contents, config):
            raise _FakeServerError("backend unavailable")

        adapter._client = SimpleNamespace(
            aio=SimpleNamespace(models=SimpleNamespace(generate_content=always_server_error))
        )

        with patch("app.adapters.gemini.asyncio.sleep", new=self._no_sleep):
            with self.assertRaises(LLMConnectionError) as ctx:
                await adapter._call_with_retry(contents=[], config=SimpleNamespace())

        self.assertIn("backend unavailable", str(ctx.exception))
        self.assertIn("after 3 retries", str(ctx.exception))

    @staticmethod
    async def _no_sleep(delay: float) -> None:
        return None


if __name__ == "__main__":
    unittest.main()