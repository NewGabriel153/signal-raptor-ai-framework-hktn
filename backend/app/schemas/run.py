from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RunCreate(BaseModel):
    agent_id: UUID
    prompt: str = Field(min_length=1)


class RunEnqueueResponse(BaseModel):
    session_id: UUID
    job_id: str
    status: str
    message: str


class ExecutionLogRead(BaseModel):
    id: UUID
    step_sequence: int
    role: str
    content: Optional[str]
    tool_calls: Optional[dict[str, Any]]
    prompt_tokens: Optional[int]
    completion_tokens: Optional[int]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RunRead(BaseModel):
    id: UUID
    agent_id: UUID
    status: str
    start_time: datetime
    end_time: Optional[datetime]
    execution_logs: list[ExecutionLogRead]

    model_config = ConfigDict(from_attributes=True)