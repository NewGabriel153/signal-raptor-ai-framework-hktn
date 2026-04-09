from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AgentCreate(BaseModel):
    name: str
    description: Optional[str] = None
    model_provider: str
    target_model: str


class AgentUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    model_provider: Optional[str] = None
    target_model: Optional[str] = None


class AgentRead(BaseModel):
    id: UUID
    name: str
    description: Optional[str]
    model_provider: str
    target_model: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AgentList(BaseModel):
    items: list[AgentRead]
    count: int