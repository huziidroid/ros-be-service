from pydantic import BaseModel, Field


class HealthCheckData(BaseModel):
    """Payload for GET /health/live — lives inside APIResponse.data."""

    alive: bool = True


class ReadinessData(BaseModel):
    """Payload for GET /health/ready — lives inside APIResponse.data."""

    ready: bool = True
    checks: dict[str, str] = Field(default_factory=dict)
