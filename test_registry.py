from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from pprint import pformat
from typing import Any, Callable


ROOT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = ROOT_DIR / "backend"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


try:
    from app.tools import get_tool_registry
except ModuleNotFoundError as exc:
    print("[FAIL] Could not import the backend tool registry.")
    print(f"Reason: {exc}")
    print("Install backend dependencies first:")
    print("  pip install -r backend/requirements.txt")
    raise SystemExit(1) from exc


logging.getLogger("app.tools.registry").disabled = True


def print_header(title: str) -> None:
    print(f"\n=== {title} ===")


def print_result(label: str, payload: dict[str, Any]) -> None:
    print(f"{label}:\n{pformat(payload, sort_dicts=False)}")


def assert_error_result(result: dict[str, Any], tool_name: str) -> None:
    assert result.get("status") == "error", f"Expected error status, got: {result}"
    assert result.get("tool_name") == tool_name, f"Unexpected tool name in result: {result}"
    assert isinstance(result.get("message"), str) and result["message"].strip(), (
        f"Expected non-empty error message, got: {result}"
    )


async def test_happy_path() -> None:
    registry = get_tool_registry()
    result = await registry.execute(
        "calculator",
        {"operation": "add", "a": 10, "b": 5},
    )
    print_result("Registry output", result)

    assert result.get("status") == "success", f"Expected success status, got: {result}"
    assert result.get("tool_name") == "calculator", f"Unexpected tool name: {result}"

    payload = result.get("result")
    assert isinstance(payload, dict), f"Expected dict result payload, got: {payload}"
    assert payload.get("operation") == "add", f"Unexpected operation payload: {payload}"
    assert payload.get("a") == 10, f"Unexpected 'a' payload: {payload}"
    assert payload.get("b") == 5, f"Unexpected 'b' payload: {payload}"
    assert payload.get("result") == 15, f"Expected calculator result 15, got: {payload}"


async def test_unregistered_tool() -> None:
    registry = get_tool_registry()
    result = await registry.execute("fake_tool", {})
    print_result("Registry output", result)

    assert_error_result(result, "fake_tool")
    assert "not registered" in result["message"].lower(), (
        f"Expected unregistered tool message, got: {result}"
    )


async def test_bad_arguments() -> None:
    registry = get_tool_registry()

    missing_operation = await registry.execute("calculator", {"a": 10, "b": 5})
    print_result("Missing argument output", missing_operation)
    assert_error_result(missing_operation, "calculator")
    assert "operation" in missing_operation["message"].lower(), (
        f"Expected missing-operation error, got: {missing_operation}"
    )

    wrong_type = await registry.execute(
        "calculator",
        {"operation": "subtract", "a": "ten", "b": 5},
    )
    print_result("Wrong type output", wrong_type)
    assert_error_result(wrong_type, "calculator")


async def test_internal_tool_crash() -> None:
    registry = get_tool_registry()
    tool_name = "temporary_crash_tool"

    if not registry.has_tool(tool_name):
        @registry.register(tool_name)
        async def temporary_crash_tool() -> None:
            raise Exception("API Timeout")

    result = await registry.execute(tool_name, {})
    print_result("Registry output", result)

    assert_error_result(result, tool_name)
    assert result["message"] == "API Timeout", f"Unexpected crash message: {result}"


async def run_case(name: str, test_func: Callable[[], Any]) -> bool:
    print_header(name)
    try:
        await test_func()
    except AssertionError as exc:
        print(f"[FAIL] {name}: {exc}")
        return False
    except Exception as exc:
        print(f"[FAIL] {name}: Unexpected exception escaped the test harness: {exc}")
        return False

    print(f"[PASS] {name}")
    return True


async def main() -> int:
    print("Signal Raptor ToolRegistry smoke test")
    print(f"Repository root: {ROOT_DIR}")
    print(f"Backend path: {BACKEND_DIR}")

    scenarios: list[tuple[str, Callable[[], Any]]] = [
        ("1. Happy Path", test_happy_path),
        ("2. Unregistered Tool", test_unregistered_tool),
        ("3. Bad Arguments (LLM Hallucination)", test_bad_arguments),
        ("4. Internal Tool Crash", test_internal_tool_crash),
    ]

    passed = 0
    for name, test_func in scenarios:
        if await run_case(name, test_func):
            passed += 1

    total = len(scenarios)
    print_header("Summary")
    print(f"Passed {passed}/{total} scenarios")

    if passed != total:
        print("[FAIL] One or more registry scenarios failed.")
        return 1

    print("[PASS] All registry scenarios passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))