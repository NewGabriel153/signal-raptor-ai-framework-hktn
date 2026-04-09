from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.models import Agent
from app.schemas import AgentCreate, AgentList, AgentRead, AgentUpdate


router = APIRouter(prefix="/agents", tags=["Agents"])


async def _get_agent_or_404(session: AsyncSession, agent_id: UUID) -> Agent:
    agent = await session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")

    return agent


@router.post("/", response_model=AgentRead, status_code=status.HTTP_201_CREATED)
async def create_agent(
    payload: AgentCreate,
    session: AsyncSession = Depends(get_db_session),
) -> Agent:
    agent = Agent(**payload.model_dump())
    session.add(agent)

    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Agent name already exists.") from exc

    await session.refresh(agent)
    return agent


@router.get("/", response_model=AgentList)
async def list_agents(session: AsyncSession = Depends(get_db_session)) -> AgentList:
    result = await session.execute(select(Agent).order_by(Agent.created_at.desc()))
    agents = result.scalars().all()
    return AgentList(items=agents, count=len(agents))


@router.get("/{agent_id}", response_model=AgentRead)
async def get_agent(agent_id: UUID, session: AsyncSession = Depends(get_db_session)) -> Agent:
    return await _get_agent_or_404(session, agent_id)


@router.patch("/{agent_id}", response_model=AgentRead)
async def update_agent(
    agent_id: UUID,
    payload: AgentUpdate,
    session: AsyncSession = Depends(get_db_session),
) -> Agent:
    agent = await _get_agent_or_404(session, agent_id)
    updates = payload.model_dump(exclude_unset=True)

    for field_name, field_value in updates.items():
        setattr(agent, field_name, field_value)

    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Agent name already exists.") from exc

    await session.refresh(agent)
    return agent


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(agent_id: UUID, session: AsyncSession = Depends(get_db_session)) -> Response:
    agent = await _get_agent_or_404(session, agent_id)
    await session.delete(agent)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)