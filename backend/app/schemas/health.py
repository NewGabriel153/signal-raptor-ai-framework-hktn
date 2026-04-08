from pydantic import BaseModel

class HealthResponse(BaseModel):
    status: str
    message: str

    class Config:
        schema_extra = {
            "example": {
                "status": "healthy",
                "message": "The service is running smoothly."
            }
        }