from __future__ import annotations

from app.tools.registry import registry


@registry.register("calculator")
async def calculator(operation: str, a: float, b: float) -> dict[str, float | str]:
    """Perform a basic arithmetic operation and return structured output."""

    normalized_operation = operation.strip().lower()

    if normalized_operation == "add":
        result = a + b
    elif normalized_operation == "subtract":
        result = a - b
    elif normalized_operation == "multiply":
        result = a * b
    elif normalized_operation == "divide":
        if b == 0:
            raise ZeroDivisionError("Cannot divide by zero.")
        result = a / b
    else:
        raise ValueError(
            "Unsupported operation. Expected one of: add, subtract, multiply, divide."
        )

    return {
        "operation": normalized_operation,
        "a": a,
        "b": b,
        "result": result,
    }