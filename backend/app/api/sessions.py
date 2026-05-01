from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import get_db_session
from app.core.pubsub import close_session_pubsub, create_session_pubsub, iter_session_events
from app.core.queue import close_queue_pool, create_queue_pool
from app.models import Agent, ExecutionLog, Session
from app.schemas import RunEnqueueResponse, RunRead, SessionCreateRequest, SessionRead, SessionRunRequest


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


async def _get_session_with_logs_or_404(
    db: AsyncSession, session_id: UUID, *, populate_existing: bool = False,
) -> Session:
    stmt = (
        select(Session)
        .options(selectinload(Session.execution_logs))
        .where(Session.id == session_id)
    )
    if populate_existing:
        stmt = stmt.execution_options(populate_existing=True)
    result = await db.execute(stmt)
    run_session = result.scalar_one_or_none()
    if run_session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.")
    return run_session


async def _get_next_step_sequence(db: AsyncSession, session_id: UUID) -> int:
    result = await db.execute(
        select(func.coalesce(func.max(ExecutionLog.step_sequence), 0)).where(ExecutionLog.session_id == session_id)
    )
    return int(result.scalar_one()) + 1


def _serialize_log_metadata(log: ExecutionLog) -> dict[str, str]:
    return {
        "log_id": str(log.id),
        "created_at": log.created_at.isoformat(),
    }


def _parse_tool_result(content: str | None) -> Any:
    if content is None:
        return None

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return content


def _build_log_events(log: ExecutionLog) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    step_sequence = log.step_sequence

    if log.role == "user":
        events.append(
            {
                "event": "user_message",
                "data": {
                    "id": str(log.id),
                    "content": log.content or "",
                    **_serialize_log_metadata(log),
                },
                "step_sequence": step_sequence,
            }
        )
        return events

    if log.role == "assistant":
        if log.content:
            events.append(
                {
                    "event": "assistant_message",
                    "data": {
                        "id": str(log.id),
                        "content": log.content,
                        **_serialize_log_metadata(log),
                    },
                    "step_sequence": step_sequence,
                }
            )

        tool_calls = log.tool_calls if isinstance(log.tool_calls, list) else []
        for tool_call in tool_calls:
            if not isinstance(tool_call, dict):
                continue
            events.append(
                {
                    "event": "tool_call",
                    "data": {
                        **tool_call,
                        **_serialize_log_metadata(log),
                    },
                    "step_sequence": step_sequence,
                }
            )

        return events

    if log.role == "tool":
        metadata = log.tool_calls if isinstance(log.tool_calls, dict) else {}
        events.append(
            {
                "event": "tool_result",
                "data": {
                    "id": metadata.get("tool_call_id"),
                    "name": metadata.get("name"),
                    "result": _parse_tool_result(log.content),
                    **_serialize_log_metadata(log),
                },
                "step_sequence": step_sequence,
            }
        )
        return events

    events.append(
        {
            "event": "status",
            "data": {
                "role": log.role,
                "message": log.content,
                **_serialize_log_metadata(log),
            },
            "step_sequence": step_sequence,
        }
    )
    return events


def _build_replay_events(run_session: Session, *, after_step: int) -> tuple[list[dict[str, Any]], int]:
    replay_events: list[dict[str, Any]] = []
    last_step = after_step

    for log in run_session.execution_logs:
        if log.step_sequence <= after_step:
            continue
        replay_events.extend(_build_log_events(log))
        last_step = max(last_step, log.step_sequence)

    return replay_events, last_step


def _build_done_event(session_id: UUID, status_value: str, step_sequence: int | None = None) -> dict[str, Any]:
    event = {
        "event": "done",
        "data": {
            "session_id": str(session_id),
            "status": status_value,
        },
    }
    if step_sequence is not None:
        event["step_sequence"] = step_sequence
    return event


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


@router.post("/{session_id}/run", response_model=RunEnqueueResponse, status_code=status.HTTP_202_ACCEPTED)
async def enqueue_session_run(
    session_id: UUID,
    payload: SessionRunRequest,
    db: AsyncSession = Depends(get_db_session),
) -> RunEnqueueResponse:
    run_session = await _get_session_or_404(db, session_id)

    if run_session.status == "running":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Session is already running.")

    next_step_sequence = await _get_next_step_sequence(db, session_id)
    run_session.status = "running"
    run_session.end_time = None
    db.add(
        ExecutionLog(
            session_id=session_id,
            step_sequence=next_step_sequence,
            role="user",
            content=payload.prompt,
        )
    )
    await db.commit()

    redis = None
    job_id = f"session:{session_id}:step:{next_step_sequence}"
    try:
        redis = await create_queue_pool()
        job = await redis.enqueue_job(
            "process_agent_run",
            str(session_id),
            payload.prompt,
            _job_id=job_id,
            _queue_name=settings.ARQ_QUEUE_NAME,
        )
        if job is None:
            raise RuntimeError("Job was not enqueued.")
    except Exception as exc:
        failed_session = await db.get(Session, session_id)
        if failed_session is not None:
            failed_session.status = "failed"
            failed_session.end_time = datetime.now(timezone.utc)
            db.add(
                ExecutionLog(
                    session_id=session_id,
                    step_sequence=next_step_sequence + 1,
                    role="system",
                    content=f"Failed to enqueue run: {exc}",
                )
            )
            await db.commit()

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redis queue is unavailable.",
        ) from exc
    finally:
        if redis is not None:
            await close_queue_pool(redis)

    return RunEnqueueResponse(
        session_id=session_id,
        job_id=job_id,
        status="running",
        message="Run accepted and queued for background processing.",
        last_step_sequence=next_step_sequence,
    )


@router.get("/{session_id}/subscribe")
async def subscribe_session(
    session_id: UUID,
    request: Request,
    after_step: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    await _get_session_or_404(db, session_id)

    async def event_stream() -> AsyncGenerator[str, None]:
        last_step = after_step
        initial_session = await _get_session_with_logs_or_404(db, session_id)
        replay_events, last_step = _build_replay_events(initial_session, after_step=last_step)

        for event in replay_events:
            yield _format_sse_event(event)

        if initial_session.status in {"completed", "failed"}:
            yield _format_sse_event(_build_done_event(session_id, initial_session.status, last_step or None))
            return

        pubsub = await create_session_pubsub(session_id)

        try:
            refreshed_session = await _get_session_with_logs_or_404(db, session_id, populate_existing=True)
            replay_events, last_step = _build_replay_events(refreshed_session, after_step=last_step)

            for event in replay_events:
                yield _format_sse_event(event)

            if refreshed_session.status in {"completed", "failed"}:
                yield _format_sse_event(_build_done_event(session_id, refreshed_session.status, last_step or None))
                return

            async for event in iter_session_events(pubsub):
                event_step = event.get("step_sequence")
                if isinstance(event_step, int) and event_step < last_step:
                    continue

                if isinstance(event_step, int):
                    last_step = event_step

                yield _format_sse_event(event)
                if event.get("event") == "done":
                    return
        except asyncio.CancelledError:
            return
        finally:
            await close_session_pubsub(session_id, pubsub)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )