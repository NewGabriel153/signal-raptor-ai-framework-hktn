from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.models import Tool
from app.schemas import ToolCreate, ToolList, ToolRead, ToolUpdate


router = APIRouter(prefix="/tools", tags=["Tools"])


async def _get_tool_or_404(session: AsyncSession, tool_id: UUID) -> Tool:
    tool = await session.get(Tool, tool_id)
    if tool is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tool not found.")

    return tool


@router.post("/", response_model=ToolRead, status_code=status.HTTP_201_CREATED)
async def create_tool(
    payload: ToolCreate,
    session: AsyncSession = Depends(get_db_session),
) -> Tool:
    tool = Tool(**payload.model_dump())
    session.add(tool)

    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Tool name already exists.") from exc

    await session.refresh(tool)
    return tool


@router.get("/", response_model=ToolList)
async def list_tools(session: AsyncSession = Depends(get_db_session)) -> ToolList:
    result = await session.execute(select(Tool).order_by(Tool.created_at.desc()))
    tools = result.scalars().all()
    return ToolList(items=tools, count=len(tools))


@router.get("/{tool_id}", response_model=ToolRead)
async def get_tool(tool_id: UUID, session: AsyncSession = Depends(get_db_session)) -> Tool:
    return await _get_tool_or_404(session, tool_id)


@router.patch("/{tool_id}", response_model=ToolRead)
async def update_tool(
    tool_id: UUID,
    payload: ToolUpdate,
    session: AsyncSession = Depends(get_db_session),
) -> Tool:
    tool = await _get_tool_or_404(session, tool_id)
    updates = payload.model_dump(exclude_unset=True)

    for field_name, field_value in updates.items():
        setattr(tool, field_name, field_value)

    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Tool name already exists.") from exc

    await session.refresh(tool)
    return tool


@router.delete("/{tool_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tool(tool_id: UUID, session: AsyncSession = Depends(get_db_session)) -> Response:
    tool = await _get_tool_or_404(session, tool_id)
    await session.delete(tool)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)