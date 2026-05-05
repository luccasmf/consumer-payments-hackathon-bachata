from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = Field(description="Service status")
    version: str = Field(description="Application version")
    environment: str = Field(description="Current environment")
