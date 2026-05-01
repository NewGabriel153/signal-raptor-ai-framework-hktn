from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.agent_tools import router as agent_tools_router
from app.api.agents import router as agents_router
from app.api.runs import router as runs_router
from app.api.sessions import router as sessions_router
from app.api.tools import router as tools_router
from app.core.database import get_db_session
from app.core.pubsub import ping_pubsub_redis
from app.schemas import HealthResponse


api_router = APIRouter()


@api_router.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check(session: AsyncSession = Depends(get_db_session)) -> HealthResponse:
    try:
        await session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is unavailable.",
        ) from exc

    try:
        redis_connected = await ping_pubsub_redis()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redis is unavailable.",
        ) from exc

    return HealthResponse(
        status="healthy",
        message="The service is running smoothly.",
        database_connected=True,
        redis_connected=redis_connected,
    )


api_router.include_router(agents_router)
api_router.include_router(tools_router)
api_router.include_router(agent_tools_router)
api_router.include_router(runs_router)
api_router.include_router(sessions_router)