from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db_session
from app.models import Agent, Tool
from app.schemas import ToolList, ToolRead


router = APIRouter(tags=["Agent Tools"])


async def _get_agent_with_tools_or_404(session: AsyncSession, agent_id: UUID) -> Agent:
    result = await session.execute(
        select(Agent)
        .options(selectinload(Agent.tools))
        .where(Agent.id == agent_id)
    )
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")

    return agent


async def _get_tool_or_404(session: AsyncSession, tool_id: UUID) -> Tool:
    tool = await session.get(Tool, tool_id)
    if tool is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tool not found.")

    return tool


@router.post("/agents/{agent_id}/tools/{tool_id}", response_model=ToolRead, status_code=status.HTTP_201_CREATED)
async def assign_tool_to_agent(
    agent_id: UUID,
    tool_id: UUID,
    session: AsyncSession = Depends(get_db_session),
) -> Tool:
    agent = await _get_agent_with_tools_or_404(session, agent_id)
    tool = await _get_tool_or_404(session, tool_id)

    if any(existing_tool.id == tool_id for existing_tool in agent.tools):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Tool is already assigned to this agent.",
        )

    agent.tools.append(tool)
    await session.commit()
    return tool


@router.get("/agents/{agent_id}/tools", response_model=ToolList)
async def list_agent_tools(
    agent_id: UUID,
    session: AsyncSession = Depends(get_db_session),
) -> ToolList:
    agent = await _get_agent_with_tools_or_404(session, agent_id)
    return ToolList(items=agent.tools, count=len(agent.tools))


@router.delete("/agents/{agent_id}/tools/{tool_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_tool_from_agent(
    agent_id: UUID,
    tool_id: UUID,
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    agent = await _get_agent_with_tools_or_404(session, agent_id)
    assigned_tool = next((tool for tool in agent.tools if tool.id == tool_id), None)

    if assigned_tool is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tool assignment not found.")

    agent.tools.remove(assigned_tool)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)