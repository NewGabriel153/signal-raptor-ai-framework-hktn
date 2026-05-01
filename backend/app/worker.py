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
from app.core.pubsub import publish_session_event
from app.core.queue import get_redis_settings
from app.models import Agent, ExecutionLog, Session
from app.orchestrator import run_agent_session
from app.tools import get_tool_registry


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


async def _mark_run_failed(session_id: UUID, reason: str) -> ExecutionLog | None:
    async with AsyncSessionFactory() as db_session:
        run_session = await db_session.get(Session, session_id)
        if run_session is None:
            return None

        next_step = await _get_next_step_sequence(db_session, session_id)
        run_session.status = "failed"
        run_session.end_time = datetime.now(timezone.utc)
        log_entry = ExecutionLog(
            session_id=session_id,
            step_sequence=next_step,
            role="system",
            content=f"Run failed in background worker: {reason}",
        )
        db_session.add(log_entry)
        await db_session.commit()
        await db_session.refresh(log_entry)
        return log_entry


async def process_agent_run(_: dict[str, Any], session_id: str, prompt: str) -> dict[str, str]:
    run_id = UUID(session_id)

    try:
        async with AsyncSessionFactory() as db_session:
            run_session = await _get_run_session(db_session, run_id)
            if run_session is None:
                return {"session_id": session_id, "status": "missing"}

            try:
                adapter = AdapterFactory.get_adapter(
                    run_session.agent.model_provider,
                    run_session.agent.target_model,
                )
            except LLMAdapterError as exc:
                message = f"Adapter setup failed: {exc}"
                error_log = await _mark_run_failed(run_id, message)
                error_event: dict[str, Any] = {
                    "event": "error",
                    "data": {"message": message},
                }
                if error_log is not None:
                    error_event["step_sequence"] = error_log.step_sequence
                    error_event["data"].update(
                        {
                            "log_id": str(error_log.id),
                            "created_at": error_log.created_at.isoformat(),
                        }
                    )
                await publish_session_event(run_id, error_event)
                await publish_session_event(
                    run_id,
                    {
                        "event": "done",
                        "data": {"session_id": session_id, "status": "failed"},
                        "step_sequence": error_log.step_sequence if error_log is not None else None,
                    },
                )
                return {"session_id": session_id, "status": "failed"}

            registry = get_tool_registry()

            async for event in run_agent_session(
                session_id=run_id,
                user_prompt=prompt,
                db=db_session,
                adapter=adapter,
                registry=registry,
                persist_user_prompt=False,
            ):
                await publish_session_event(run_id, event)

            refreshed_session = await db_session.get(Session, run_id)
            return {
                "session_id": session_id,
                "status": refreshed_session.status if refreshed_session is not None else "completed",
            }
    except Exception as exc:
        error_log = await _mark_run_failed(run_id, str(exc))
        error_event: dict[str, Any] = {
            "event": "error",
            "data": {"message": f"Run failed in background worker: {exc}"},
        }
        done_event: dict[str, Any] = {
            "event": "done",
            "data": {"session_id": session_id, "status": "failed"},
        }
        if error_log is not None:
            error_event["step_sequence"] = error_log.step_sequence
            error_event["data"].update(
                {
                    "log_id": str(error_log.id),
                    "created_at": error_log.created_at.isoformat(),
                }
            )
            done_event["step_sequence"] = error_log.step_sequence

        try:
            await publish_session_event(run_id, error_event)
            await publish_session_event(run_id, done_event)
        except Exception:
            pass
        raise

    return {"session_id": session_id, "status": "completed"}


class WorkerSettings:
    functions = [process_agent_run]
    redis_settings = get_redis_settings()
    queue_name = settings.ARQ_QUEUE_NAME
    max_jobs = settings.ARQ_MAX_JOBS
    job_timeout = 300