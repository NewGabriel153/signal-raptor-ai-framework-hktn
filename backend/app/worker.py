from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.adapters import AdapterFactory, LLMAdapterError
from app.core.config import settings
from app.core.database import AsyncSessionFactory
from app.core.queue import get_redis_settings
from app.models import Agent, ExecutionLog, Session


async def _get_run_session(session: AsyncSession, session_id: UUID) -> Session | None:
    result = await session.execute(
        select(Session)
        .options(
            selectinload(Session.agent).selectinload(Agent.prompt_versions),
            selectinload(Session.agent).selectinload(Agent.tools),
        )
        .where(Session.id == session_id)
    )
    return result.scalar_one_or_none()


async def _get_next_step_sequence(session: AsyncSession, session_id: UUID) -> int:
    result = await session.execute(
        select(func.coalesce(func.max(ExecutionLog.step_sequence), 0)).where(ExecutionLog.session_id == session_id)
    )
    return int(result.scalar_one()) + 1


def _append_log(
    db_session: AsyncSession,
    session_id: UUID,
    step_sequence: int,
    role: str,
    content: str,
    tool_calls: dict[str, Any] | None = None,
) -> int:
    db_session.add(
        ExecutionLog(
            session_id=session_id,
            step_sequence=step_sequence,
            role=role,
            content=content,
            tool_calls=tool_calls,
        )
    )
    return step_sequence + 1


def _build_messages(agent: Agent, prompt: str) -> list[dict[str, Any]]:
    """Assemble the standardized message list sent to the LLM adapter."""
    messages: list[dict[str, Any]] = []
    active_prompt = next((pv for pv in agent.prompt_versions if pv.is_active), None)
    if active_prompt:
        messages.append({"role": "system", "content": active_prompt.system_prompt_template})
    messages.append({"role": "user", "content": prompt})
    return messages


def _build_tool_schemas(agent: Agent) -> list[dict[str, Any]]:
    """Convert the agent's registered tools into adapter-ready dicts."""
    return [
        {
            "name": tool.name,
            "description": tool.description or "",
            "parameters": tool.json_schema,
        }
        for tool in agent.tools
    ]


def _build_scaffold_response(agent: Agent, prompt: str) -> str:
    """Fallback placeholder when no LLM adapter is available."""
    return (
        f"[scaffold] Queued run completed for agent '{agent.name}'. "
        f"Prompt received: {prompt}. "
        "Set GOOGLE_API_KEY to enable real LLM responses."
    )


async def _mark_run_failed(session_id: UUID, reason: str) -> None:
    async with AsyncSessionFactory() as db_session:
        run_session = await db_session.get(Session, session_id)
        if run_session is None:
            return

        next_step = await _get_next_step_sequence(db_session, session_id)
        run_session.status = "failed"
        run_session.end_time = datetime.now(timezone.utc)
        _append_log(
            db_session,
            session_id,
            next_step,
            "system",
            f"Run failed in background worker: {reason}",
        )
        await db_session.commit()


async def process_agent_run(_: dict[str, Any], session_id: str, prompt: str) -> dict[str, str]:
    run_id = UUID(session_id)

    try:
        async with AsyncSessionFactory() as db_session:
            run_session = await _get_run_session(db_session, run_id)
            if run_session is None:
                return {"session_id": session_id, "status": "missing"}

            if run_session.status == "completed":
                return {"session_id": session_id, "status": run_session.status}

            next_step = await _get_next_step_sequence(db_session, run_id)
            run_session.status = "running"
            next_step = _append_log(
                db_session,
                run_id,
                next_step,
                "system",
                f"Worker picked up run for agent '{run_session.agent.name}'.",
            )

            agent = run_session.agent

            # --- attempt real LLM call via adapter -------------------------
            try:
                adapter = AdapterFactory.get_adapter(agent.model_provider, agent.target_model)
            except LLMAdapterError as exc:
                next_step = _append_log(
                    db_session, run_id, next_step, "system",
                    f"LLM adapter unavailable ({exc}), returning scaffold response.",
                )
                _append_log(
                    db_session, run_id, next_step, "assistant",
                    _build_scaffold_response(agent, prompt),
                )
                run_session.status = "completed"
                run_session.end_time = datetime.now(timezone.utc)
                await db_session.commit()
                return {"session_id": session_id, "status": "completed"}

            messages = _build_messages(agent, prompt)
            tool_schemas = _build_tool_schemas(agent)

            next_step = _append_log(
                db_session, run_id, next_step, "system",
                f"Calling {agent.model_provider}/{agent.target_model} via adapter\u2026",
            )

            llm_response = await adapter.generate(
                messages=messages,
                tools=tool_schemas if tool_schemas else None,
            )

            tool_calls_data = (
                [tc.model_dump() for tc in llm_response.tool_calls]
                if llm_response.tool_calls
                else None
            )

            db_session.add(
                ExecutionLog(
                    session_id=run_id,
                    step_sequence=next_step,
                    role="assistant",
                    content=llm_response.content,
                    tool_calls=tool_calls_data,
                    prompt_tokens=llm_response.prompt_tokens,
                    completion_tokens=llm_response.completion_tokens,
                )
            )

            run_session.status = "completed"
            run_session.end_time = datetime.now(timezone.utc)
            await db_session.commit()
    except Exception as exc:
        await _mark_run_failed(run_id, str(exc))
        raise

    return {"session_id": session_id, "status": "completed"}


class WorkerSettings:
    functions = [process_agent_run]
    redis_settings = get_redis_settings()
    queue_name = settings.ARQ_QUEUE_NAME
    max_jobs = settings.ARQ_MAX_JOBS