from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    status: str
    message: str
    database_connected: bool
    redis_connected: bool

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "healthy",
                "message": "The service is running smoothly.",
                "database_connected": True,
                "redis_connected": True,
            }
        }
    )