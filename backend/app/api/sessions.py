from __future__ import annotations

from collections.abc import AsyncGenerator
import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.adapters import AdapterFactory, LLMAdapterError
from app.core.database import get_db_session
from app.models import Agent, ExecutionLog, Session
from app.orchestrator import run_agent_session
from app.schemas import ExecutionLogRead, RunRead, SessionCreateRequest, SessionRead, SessionRunRequest
from app.tools import get_tool_registry


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sessions", tags=["Sessions"])


def _format_sse_event(event: dict[str, Any]) -> str:
    payload = json.dumps(event, separators=(",", ":"))
    return f"data: {payload}\n\n"


async def _get_session_or_404(db: AsyncSession, session_id: UUID) -> Session:
    result = await db.execute(
        select(Session)
        .options(selectinload(Session.agent))
        .where(Session.id == session_id)
    )
    run_session = result.scalar_one_or_none()
    if run_session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.")
    return run_session


async def _get_next_step_sequence(db: AsyncSession, session_id: UUID) -> int:
    result = await db.execute(
        select(func.coalesce(func.max(ExecutionLog.step_sequence), 0)).where(ExecutionLog.session_id == session_id)
    )
    return int(result.scalar_one()) + 1


async def _safe_rollback(db: AsyncSession) -> None:
    try:
        await db.rollback()
    except Exception:
        logger.exception("Failed to rollback session stream database transaction.")


async def _persist_stream_setup_failure(
    db: AsyncSession,
    *,
    session_id: UUID,
    user_prompt: str,
    message: str,
) -> None:
    await _safe_rollback(db)

    try:
        run_session = await db.get(Session, session_id)
        if run_session is None:
            return

        next_step_sequence = await _get_next_step_sequence(db, session_id)
        run_session.status = "failed"
        run_session.end_time = datetime.now(timezone.utc)
        db.add(
            ExecutionLog(
                session_id=session_id,
                step_sequence=next_step_sequence,
                role="user",
                content=user_prompt,
            )
        )
        db.add(
            ExecutionLog(
                session_id=session_id,
                step_sequence=next_step_sequence + 1,
                role="system",
                content=message,
            )
        )
        await db.commit()
    except Exception:
        logger.exception("Failed to persist stream setup failure for session %s.", session_id)
        await _safe_rollback(db)


@router.get("/", response_model=list[SessionRead])
async def list_sessions(
    db: AsyncSession = Depends(get_db_session),
) -> list[Session]:
    result = await db.execute(
        select(Session).order_by(Session.start_time.desc())
    )
    return list(result.scalars().all())


@router.get("/{session_id}/logs", response_model=RunRead)
async def get_session_logs(
    session_id: UUID,
    db: AsyncSession = Depends(get_db_session),
) -> Session:
    result = await db.execute(
        select(Session)
        .options(selectinload(Session.execution_logs))
        .where(Session.id == session_id)
    )
    run_session = result.scalar_one_or_none()
    if run_session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.")
    return run_session


@router.post("/", response_model=SessionRead, status_code=status.HTTP_201_CREATED)
async def create_session(
    payload: SessionCreateRequest,
    db: AsyncSession = Depends(get_db_session),
) -> Session:
    agent = await db.get(Agent, payload.agent_id)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")

    session_record = Session(agent_id=payload.agent_id, status="active")
    db.add(session_record)
    await db.commit()
    await db.refresh(session_record)
    return session_record


@router.post("/{session_id}/run")
async def run_session_stream(
    session_id: UUID,
    payload: SessionRunRequest,
    db: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    run_session = await _get_session_or_404(db, session_id)
    provider = run_session.agent.model_provider
    target_model = run_session.agent.target_model
    registry = get_tool_registry()

    async def event_stream() -> AsyncGenerator[str, None]:
        try:
            adapter = AdapterFactory.get_adapter(provider, target_model)
        except LLMAdapterError as exc:
            message = f"Adapter setup failed: {exc}"
            await _persist_stream_setup_failure(
                db,
                session_id=session_id,
                user_prompt=payload.prompt,
                message=message,
            )
            yield _format_sse_event({"event": "error", "data": message})
            yield _format_sse_event({"event": "done"})
            return

        async for event in run_agent_session(
            session_id=session_id,
            user_prompt=payload.prompt,
            db=db,
            adapter=adapter,
            registry=registry,
        ):
            yield _format_sse_event(event)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )