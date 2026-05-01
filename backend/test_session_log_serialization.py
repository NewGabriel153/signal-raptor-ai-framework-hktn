from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4


BACKEND_DIR = Path(__file__).resolve().parent

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from app.schemas.run import RunRead


class SessionLogSerializationTests(unittest.TestCase):
    def test_run_read_accepts_mixed_tool_call_payloads(self) -> None:
        now = datetime.now(timezone.utc)
        session_payload = SimpleNamespace(
            id=uuid4(),
            agent_id=uuid4(),
            status="completed",
            start_time=now,
            end_time=now,
            execution_logs=[
                SimpleNamespace(
                    id=uuid4(),
                    step_sequence=1,
                    role="assistant",
                    content="Using a tool.",
                    tool_calls=[
                        {
                            "id": "call_1",
                            "name": "calculator",
                            "arguments": {"operation": "add", "a": 1, "b": 2},
                        }
                    ],
                    prompt_tokens=12,
                    completion_tokens=8,
                    created_at=now,
                ),
                SimpleNamespace(
                    id=uuid4(),
                    step_sequence=2,
                    role="tool",
                    content='{"result": 3}',
                    tool_calls={"name": "calculator", "tool_call_id": "call_1"},
                    prompt_tokens=None,
                    completion_tokens=None,
                    created_at=now,
                ),
            ],
        )

        payload = RunRead.model_validate(session_payload)

        self.assertIsInstance(payload.execution_logs[0].tool_calls, list)
        self.assertEqual(payload.execution_logs[0].tool_calls[0]["name"], "calculator")
        self.assertEqual(payload.execution_logs[1].tool_calls["tool_call_id"], "call_1")


if __name__ == "__main__":
    unittest.main()