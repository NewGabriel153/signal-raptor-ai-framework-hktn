from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import get_db_session
from app.core.queue import close_queue_pool, create_queue_pool
from app.models import Agent, ExecutionLog, Session
from app.schemas import RunCreate, RunEnqueueResponse, RunRead


router = APIRouter(prefix="/runs", tags=["Runs"])


async def _get_run_or_404(session: AsyncSession, run_id: UUID) -> Session:
    result = await session.execute(
        select(Session)
        .options(selectinload(Session.execution_logs))
        .where(Session.id == run_id)
    )
    run_session = result.scalar_one_or_none()
    if run_session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run session not found.")

    return run_session


@router.post("/", response_model=RunEnqueueResponse, status_code=status.HTTP_202_ACCEPTED)
async def enqueue_run(
    payload: RunCreate,
    session: AsyncSession = Depends(get_db_session),
) -> RunEnqueueResponse:
    agent = await session.get(Agent, payload.agent_id)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")

    run_session = Session(agent_id=payload.agent_id, status="queued")
    session.add(run_session)
    await session.flush()

    session.add(
        ExecutionLog(
            session_id=run_session.id,
            step_sequence=1,
            role="user",
            content=payload.prompt,
        )
    )
    await session.commit()

    redis = None
    job_id = f"run:{run_session.id}"
    try:
        redis = await create_queue_pool()
        job = await redis.enqueue_job(
            "process_agent_run",
            str(run_session.id),
            payload.prompt,
            _job_id=job_id,
            _queue_name=settings.ARQ_QUEUE_NAME,
        )
        if job is None:
            raise RuntimeError("Job was not enqueued.")
    except Exception as exc:
        failed_session = await session.get(Session, run_session.id)
        if failed_session is not None:
            failed_session.status = "failed"
            failed_session.end_time = datetime.now(timezone.utc)
            session.add(
                ExecutionLog(
                    session_id=failed_session.id,
                    step_sequence=2,
                    role="system",
                    content=f"Failed to enqueue run: {exc}",
                )
            )
            await session.commit()

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redis queue is unavailable.",
        ) from exc
    finally:
        if redis is not None:
            await close_queue_pool(redis)

    return RunEnqueueResponse(
        session_id=run_session.id,
        job_id=job_id,
        status="queued",
        message="Run accepted and queued for background processing.",
    )


@router.get("/{run_id}", response_model=RunRead)
async def get_run(
    run_id: UUID,
    session: AsyncSession = Depends(get_db_session),
) -> Session:
    return await _get_run_or_404(session, run_id)