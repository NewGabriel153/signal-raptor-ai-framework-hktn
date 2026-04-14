from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable
from typing import Any, Literal, TypeVar

from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel


logger = logging.getLogger(__name__)

ToolCallable = Callable[..., Awaitable[Any]]
ToolCallableType = TypeVar("ToolCallableType", bound=ToolCallable)


class ToolExecutionResult(BaseModel):
    """Standardized payload returned after any tool execution attempt."""

    status: Literal["success", "error"]
    tool_name: str
    result: Any | None = None
    message: str | None = None


class ToolRegistry:
    """Registry for asynchronous tool callables used by the ReAct loop."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolCallable] = {}

    def register(self, name: str | None = None) -> Callable[[ToolCallableType], ToolCallableType]:
        """Register an async callable under *name* or its function name."""

        def decorator(func: ToolCallableType) -> ToolCallableType:
            tool_name = (name or func.__name__).strip()
            if not tool_name:
                raise ValueError("Tool name cannot be empty.")

            if not self._is_async_callable(func):
                raise TypeError(f"Tool '{tool_name}' must be an async callable.")

            existing = self._tools.get(tool_name)
            if existing is not None and existing is not func:
                raise ValueError(f"Tool '{tool_name}' is already registered.")

            self._tools[tool_name] = func
            return func

        return decorator

    async def execute(self, tool_name: str, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Execute a registered tool and always return a JSON-serializable dict."""

        try:
            if not isinstance(tool_name, str):
                raise TypeError("Tool name must be provided as a string.")

            normalized_name = tool_name.strip()
            if not normalized_name:
                return jsonable_encoder(
                    ToolExecutionResult(
                        status="error",
                        tool_name=tool_name,
                        message="Tool name cannot be empty.",
                    ).model_dump(exclude_none=True)
                )

            tool = self._tools.get(normalized_name)
            if tool is None:
                return jsonable_encoder(
                    ToolExecutionResult(
                        status="error",
                        tool_name=normalized_name,
                        message=f"Tool '{normalized_name}' is not registered.",
                    ).model_dump(exclude_none=True)
                )

            if kwargs is None:
                payload: dict[str, Any] = {}
            elif not isinstance(kwargs, dict):
                raise TypeError("Tool arguments must be provided as a dictionary.")
            else:
                payload = dict(kwargs)

            result = await tool(**payload)
            return jsonable_encoder(
                ToolExecutionResult(
                    status="success",
                    tool_name=normalized_name,
                    result=result,
                ).model_dump(exclude_none=True)
            )
        except asyncio.TimeoutError:
            logger.warning("Tool '%s' timed out during execution.", normalized_name, exc_info=True)
            return jsonable_encoder(
                ToolExecutionResult(
                    status="error",
                    tool_name=normalized_name,
                    message=f"Tool '{normalized_name}' timed out during execution.",
                ).model_dump(exclude_none=True)
            )
        except Exception as exc:
            normalized_name = tool_name if isinstance(tool_name, str) else str(tool_name)
            logger.exception("Tool '%s' failed during execution.", normalized_name)
            message = str(exc).strip() or exc.__class__.__name__
            return jsonable_encoder(
                ToolExecutionResult(
                    status="error",
                    tool_name=normalized_name,
                    message=message,
                ).model_dump(exclude_none=True)
            )

    def get(self, name: str) -> ToolCallable | None:
        """Return a registered tool by name, if present."""

        return self._tools.get(name.strip())

    def has_tool(self, name: str) -> bool:
        """Check whether a tool has been registered."""

        return self.get(name) is not None

    def list_tools(self) -> list[str]:
        """Return all registered tool names in deterministic order."""

        return sorted(self._tools)

    @staticmethod
    def _is_async_callable(candidate: Callable[..., Any]) -> bool:
        return inspect.iscoroutinefunction(candidate) or inspect.iscoroutinefunction(
            getattr(candidate, "__call__", None)
        )


registry = ToolRegistry()


def get_tool_registry() -> ToolRegistry:
    """FastAPI dependency entry point for the shared tool registry."""

    return registry