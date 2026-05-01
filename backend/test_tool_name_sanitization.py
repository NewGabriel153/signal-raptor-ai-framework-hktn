from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


BACKEND_DIR = Path(__file__).resolve().parent

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


_ANTHROPIC_IMPORT_ERROR: ModuleNotFoundError | None = None
_OPENAI_IMPORT_ERROR: ModuleNotFoundError | None = None

try:
    from app.adapters.anthropic import (
        _build_anthropic_tools,
        _convert_messages as anthropic_convert_messages,
        _extract_tool_calls as anthropic_extract_tool_calls,
    )
except ModuleNotFoundError as exc:
    _ANTHROPIC_IMPORT_ERROR = exc
    _build_anthropic_tools = None

try:
    from app.adapters.openai import (
        _build_oai_tools,
        _convert_messages as openai_convert_messages,
        _extract_tool_calls as openai_extract_tool_calls,
    )
except ModuleNotFoundError as exc:
    _OPENAI_IMPORT_ERROR = exc
    _build_oai_tools = None


@unittest.skipIf(
    _build_anthropic_tools is None,
    "Backend Anthropic dependencies are not installed. "
    f"Run 'pip install -r backend/requirements.txt' first. ({_ANTHROPIC_IMPORT_ERROR})",
)
class AnthropicToolNameSanitizationTests(unittest.TestCase):
    def test_build_tools_sanitises_invalid_name(self) -> None:
        tools = [
            {
                "name": "bad tool.v1",
                "description": "Test tool.",
                "parameters": {"type": "object", "properties": {}},
            }
        ]
        original_to_provider = {"bad tool.v1": "bad_tool_v1_a8b1c2d3"}

        provider_tools = _build_anthropic_tools(tools, original_to_provider)

        self.assertEqual(provider_tools[0]["name"], "bad_tool_v1_a8b1c2d3")

    def test_convert_messages_uses_provider_tool_name(self) -> None:
        _, converted = anthropic_convert_messages(
            [
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "name": "bad tool.v1",
                            "arguments": {"value": 3},
                        }
                    ],
                }
            ],
            {"bad tool.v1": "bad_tool_v1_a8b1c2d3"},
        )

        self.assertEqual(converted[0]["content"][0]["name"], "bad_tool_v1_a8b1c2d3")

    def test_extract_tool_calls_maps_back_to_original_name(self) -> None:
        content_blocks = [
            SimpleNamespace(
                type="tool_use",
                id="call_1",
                name="bad_tool_v1_a8b1c2d3",
                input={"value": 3},
            )
        ]

        calls = anthropic_extract_tool_calls(
            content_blocks,
            {"bad_tool_v1_a8b1c2d3": "bad tool.v1"},
        )

        self.assertEqual(calls[0].name, "bad tool.v1")
        self.assertEqual(calls[0].arguments, {"value": 3})


@unittest.skipIf(
    _build_oai_tools is None,
    "Backend OpenAI dependencies are not installed. "
    f"Run 'pip install -r backend/requirements.txt' first. ({_OPENAI_IMPORT_ERROR})",
)
class OpenAIToolNameSanitizationTests(unittest.TestCase):
    def test_build_tools_sanitises_invalid_name(self) -> None:
        tools = [
            {
                "name": "bad tool.v1",
                "description": "Test tool.",
                "parameters": {"type": "object", "properties": {}},
            }
        ]
        original_to_provider = {"bad tool.v1": "bad_tool_v1_a8b1c2d3"}

        provider_tools = _build_oai_tools(tools, original_to_provider)

        self.assertEqual(provider_tools[0]["function"]["name"], "bad_tool_v1_a8b1c2d3")

    def test_convert_messages_uses_provider_tool_name(self) -> None:
        converted = openai_convert_messages(
            [
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "name": "bad tool.v1",
                            "arguments": {"value": 3},
                        }
                    ],
                }
            ],
            {"bad tool.v1": "bad_tool_v1_a8b1c2d3"},
        )

        tool_call = converted[0]["tool_calls"][0]
        self.assertEqual(tool_call["function"]["name"], "bad_tool_v1_a8b1c2d3")
        self.assertEqual(tool_call["function"]["arguments"], '{"value": 3}')

    def test_extract_tool_calls_maps_back_to_original_name(self) -> None:
        choice_tool_calls = [
            SimpleNamespace(
                id="call_1",
                function=SimpleNamespace(name="bad_tool_v1_a8b1c2d3", arguments='{"value": 3}'),
            )
        ]

        calls = openai_extract_tool_calls(
            choice_tool_calls,
            {"bad_tool_v1_a8b1c2d3": "bad tool.v1"},
        )

        self.assertEqual(calls[0].name, "bad tool.v1")
        self.assertEqual(calls[0].arguments, {"value": 3})


if __name__ == "__main__":
    unittest.main()