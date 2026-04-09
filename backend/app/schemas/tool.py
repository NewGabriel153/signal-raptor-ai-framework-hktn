from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ToolCreate(BaseModel):
    name: str
    description: Optional[str] = None
    json_schema: dict[str, Any]
    python_function_name: str


class ToolUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    json_schema: Optional[dict[str, Any]] = None
    python_function_name: Optional[str] = None


class ToolRead(BaseModel):
    id: UUID
    name: str
    description: Optional[str]
    json_schema: dict[str, Any]
    python_function_name: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ToolList(BaseModel):
    items: list[ToolRead]
    count: int