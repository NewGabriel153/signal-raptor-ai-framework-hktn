from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator, Iterator
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.adapters import BaseLLMAdapter, LLMAdapterError, ToolCallRequest
from app.models import Agent, ExecutionLog, Session
from app.tools import ToolRegistry


logger = logging.getLogger(__name__)

MAX_ITERATIONS = 5

EventPayload = dict[str, Any]
ConversationMessage = dict[str, Any]


def _build_event(
    event: str,
    data: Any | None = None,
    *,
    step_sequence: int | None = None,
) -> EventPayload:
    payload: EventPayload = {"event": event}
    if data is not None:
        payload["data"] = data
    if step_sequence is not None:
        payload["step_sequence"] = step_sequence
    return payload


async def _load_session_with_agent(db: AsyncSession, session_id: UUID) -> Session | None:
    result = await db.execute(
        select(Session)
        .options(
            selectinload(Session.agent).selectinload(Agent.prompt_versions),
            selectinload(Session.agent).selectinload(Agent.tools),
            selectinload(Session.execution_logs),
        )
        .where(Session.id == session_id)
    )
    return result.scalar_one_or_none()


async def _get_next_step_sequence(db: AsyncSession, session_id: UUID) -> int:
    result = await db.execute(
        select(func.coalesce(func.max(ExecutionLog.step_sequence), 0)).where(ExecutionLog.session_id == session_id)
    )
    return int(result.scalar_one()) + 1


def _serialize_tool_calls(tool_calls: list[ToolCallRequest]) -> list[dict[str, Any]]:
    return [tool_call.model_dump() for tool_call in tool_calls]


def _execution_log_to_message(log: ExecutionLog) -> ConversationMessage | None:
    if log.role == "user":
        return {"role": "user", "content": log.content or ""}

    if log.role == "assistant":
        message: ConversationMessage = {
            "role": "assistant",
            "content": log.content or "",
        }
        if isinstance(log.tool_calls, list) and log.tool_calls:
            message["tool_calls"] = [
                tool_call for tool_call in log.tool_calls if isinstance(tool_call, dict)
            ]
        return message

    if log.role == "tool":
        metadata = log.tool_calls if isinstance(log.tool_calls, dict) else {}
        tool_name = metadata.get("name")
        tool_call_id = metadata.get("tool_call_id")
        if not tool_name or not tool_call_id:
            return None
        return {
            "role": "tool",
            "name": str(tool_name),
            "tool_call_id": str(tool_call_id),
            "content": log.content or "",
        }

    return None


def _build_conversation_history(run_session: Session) -> list[ConversationMessage]:
    messages: list[ConversationMessage] = []

    active_prompt = next(
        (prompt for prompt in run_session.agent.prompt_versions if prompt.is_active),
        None,
    )
    if active_prompt is not None:
        messages.append({"role": "system", "content": active_prompt.system_prompt_template})

    for execution_log in run_session.execution_logs:
        message = _execution_log_to_message(execution_log)
        if message is not None:
            messages.append(message)

    return messages


def _build_tool_schemas(agent: Agent) -> list[dict[str, Any]]:
    return [
        {
            "name": tool.name,
            "description": tool.description or "",
            "parameters": tool.json_schema,
        }
        for tool in agent.tools
    ]


def _build_tool_name_to_function(agent: Agent) -> dict[str, str]:
    """Map DB tool names to their Python registry function names."""
    return {tool.name: tool.python_function_name for tool in agent.tools}


def _iter_text_chunks(text: str, chunk_size: int = 48) -> Iterator[str]:
    for start in range(0, len(text), chunk_size):
        yield text[start : start + chunk_size]


def _log_metadata(log_entry: ExecutionLog) -> dict[str, str]:
    return {
        "log_id": str(log_entry.id),
        "created_at": log_entry.created_at.isoformat(),
    }


async def _persist_execution_log(
    db: AsyncSession,
    *,
    session_id: UUID,
    step_sequence: int,
    role: str,
    content: str | None,
    tool_calls: dict[str, Any] | list[dict[str, Any]] | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
) -> ExecutionLog:
    log_entry = ExecutionLog(
        session_id=session_id,
        step_sequence=step_sequence,
        role=role,
        content=content,
        tool_calls=tool_calls,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )
    db.add(log_entry)
    await db.commit()
    await db.refresh(log_entry)
    return log_entry


async def _safe_rollback(db: AsyncSession) -> None:
    try:
        await db.rollback()
    except Exception:
        logger.exception("Failed to rollback database session.")


async def _persist_terminal_error(
    db: AsyncSession,
    *,
    session_id: UUID,
    message: str,
) -> ExecutionLog | None:
    await _safe_rollback(db)

    try:
        run_session = await db.get(Session, session_id)
        if run_session is None:
            return None

        run_session.status = "failed"
        run_session.end_time = datetime.now(timezone.utc)
        next_step_sequence = await _get_next_step_sequence(db, session_id)
        return await _persist_execution_log(
            db,
            session_id=session_id,
            step_sequence=next_step_sequence,
            role="system",
            content=message,
        )
    except Exception:
        logger.exception("Failed to persist terminal error for session %s.", session_id)
        await _safe_rollback(db)
        return None


async def run_agent_session(
    session_id: UUID,
    user_prompt: str,
    db: AsyncSession,
    adapter: BaseLLMAdapter,
    registry: ToolRegistry,
    *,
    persist_user_prompt: bool = True,
) -> AsyncGenerator[EventPayload, None]:
    try:
        run_session = await _load_session_with_agent(db, session_id)
        if run_session is None:
            yield _build_event("error", {"message": "Session not found."})
            yield _build_event("done", {"session_id": str(session_id), "status": "failed"})
            return

        conversation_history = _build_conversation_history(run_session)
        tool_schemas = _build_tool_schemas(run_session.agent)
        tool_name_to_function = _build_tool_name_to_function(run_session.agent)
        next_step_sequence = await _get_next_step_sequence(db, session_id)

        if run_session.status != "running" or run_session.end_time is not None:
            run_session.status = "running"
            run_session.end_time = None
            await db.commit()

        if persist_user_prompt:
            user_log = await _persist_execution_log(
                db,
                session_id=session_id,
                step_sequence=next_step_sequence,
                role="user",
                content=user_prompt,
            )
            next_step_sequence = user_log.step_sequence + 1
            conversation_history.append({"role": "user", "content": user_prompt})
            yield _build_event(
                "user_message",
                {
                    "id": str(user_log.id),
                    "content": user_prompt,
                    **_log_metadata(user_log),
                },
                step_sequence=user_log.step_sequence,
            )

        for _ in range(MAX_ITERATIONS):
            try:
                llm_response = await adapter.generate(
                    messages=conversation_history,
                    tools=tool_schemas or None,
                )
            except LLMAdapterError as exc:
                message = f"Adapter error: {exc}"
                error_log = await _persist_terminal_error(db, session_id=session_id, message=message)
                error_data: dict[str, Any] = {"message": message}
                error_step_sequence: int | None = None
                if error_log is not None:
                    error_data.update(_log_metadata(error_log))
                    error_step_sequence = error_log.step_sequence
                yield _build_event("error", error_data, step_sequence=error_step_sequence)
                yield _build_event(
                    "done",
                    {"session_id": str(session_id), "status": "failed"},
                    step_sequence=error_step_sequence,
                )
                return

            if llm_response.tool_calls:
                serialized_tool_calls = _serialize_tool_calls(llm_response.tool_calls)
                assistant_log = await _persist_execution_log(
                    db,
                    session_id=session_id,
                    step_sequence=next_step_sequence,
                    role="assistant",
                    content=llm_response.content,
                    tool_calls=serialized_tool_calls,
                    prompt_tokens=llm_response.prompt_tokens,
                    completion_tokens=llm_response.completion_tokens,
                )
                next_step_sequence = assistant_log.step_sequence + 1
                assistant_message: ConversationMessage = {
                    "role": "assistant",
                    "tool_calls": serialized_tool_calls,
                }
                if llm_response.content:
                    assistant_message["content"] = llm_response.content
                    yield _build_event(
                        "assistant_message",
                        {
                            "id": str(assistant_log.id),
                            "content": llm_response.content,
                            **_log_metadata(assistant_log),
                        },
                        step_sequence=assistant_log.step_sequence,
                    )
                conversation_history.append(assistant_message)

                for tool_call in llm_response.tool_calls:
                    yield _build_event(
                        "tool_call",
                        {
                            **tool_call.model_dump(),
                            **_log_metadata(assistant_log),
                        },
                        step_sequence=assistant_log.step_sequence,
                    )

                    registry_name = tool_name_to_function.get(tool_call.name, tool_call.name)
                    tool_result = await registry.execute(registry_name, tool_call.arguments)
                    tool_content = json.dumps(tool_result)
                    tool_log = await _persist_execution_log(
                        db,
                        session_id=session_id,
                        step_sequence=next_step_sequence,
                        role="tool",
                        content=tool_content,
                        tool_calls={
                            "name": tool_call.name,
                            "tool_call_id": tool_call.id,
                        },
                    )
                    next_step_sequence = tool_log.step_sequence + 1
                    conversation_history.append(
                        {
                            "role": "tool",
                            "name": tool_call.name,
                            "tool_call_id": tool_call.id,
                            "content": tool_content,
                        }
                    )
                    yield _build_event(
                        "tool_result",
                        {
                            "id": tool_call.id,
                            "name": tool_call.name,
                            "result": tool_result,
                            **_log_metadata(tool_log),
                        },
                        step_sequence=tool_log.step_sequence,
                    )

                continue

            if llm_response.content:
                run_session.status = "completed"
                run_session.end_time = datetime.now(timezone.utc)
                assistant_log = await _persist_execution_log(
                    db,
                    session_id=session_id,
                    step_sequence=next_step_sequence,
                    role="assistant",
                    content=llm_response.content,
                    prompt_tokens=llm_response.prompt_tokens,
                    completion_tokens=llm_response.completion_tokens,
                )
                for chunk in _iter_text_chunks(llm_response.content):
                    yield _build_event(
                        "token",
                        {
                            "id": str(assistant_log.id),
                            "chunk": chunk,
                            **_log_metadata(assistant_log),
                        },
                        step_sequence=assistant_log.step_sequence,
                    )
                yield _build_event(
                    "assistant_message",
                    {
                        "id": str(assistant_log.id),
                        "content": llm_response.content,
                        **_log_metadata(assistant_log),
                    },
                    step_sequence=assistant_log.step_sequence,
                )
                yield _build_event(
                    "done",
                    {"session_id": str(session_id), "status": "completed"},
                    step_sequence=assistant_log.step_sequence,
                )
                return

            message = "LLM response did not include text or tool calls."
            error_log = await _persist_terminal_error(db, session_id=session_id, message=message)
            error_data: dict[str, Any] = {"message": message}
            error_step_sequence: int | None = None
            if error_log is not None:
                error_data.update(_log_metadata(error_log))
                error_step_sequence = error_log.step_sequence
            yield _build_event("error", error_data, step_sequence=error_step_sequence)
            yield _build_event(
                "done",
                {"session_id": str(session_id), "status": "failed"},
                step_sequence=error_step_sequence,
            )
            return

        message = f"Maximum iterations exceeded ({MAX_ITERATIONS})."
        error_log = await _persist_terminal_error(db, session_id=session_id, message=message)
        error_data: dict[str, Any] = {"message": message}
        error_step_sequence: int | None = None
        if error_log is not None:
            error_data.update(_log_metadata(error_log))
            error_step_sequence = error_log.step_sequence
        yield _build_event("error", error_data, step_sequence=error_step_sequence)
        yield _build_event(
            "done",
            {"session_id": str(session_id), "status": "failed"},
            step_sequence=error_step_sequence,
        )
    except Exception as exc:
        logger.exception("Unexpected failure while running agent session %s.", session_id)
        message = f"Run failed: {exc}"
        error_log = await _persist_terminal_error(db, session_id=session_id, message=message)
        error_data: dict[str, Any] = {"message": message}
        error_step_sequence: int | None = None
        if error_log is not None:
            error_data.update(_log_metadata(error_log))
            error_step_sequence = error_log.step_sequence
        yield _build_event("error", error_data, step_sequence=error_step_sequence)
        yield _build_event(
            "done",
            {"session_id": str(session_id), "status": "failed"},
            step_sequence=error_step_sequence,
        )