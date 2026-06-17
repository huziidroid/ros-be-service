from typing import Literal

from pydantic import BaseModel, Field


class HealthCheckResponse(BaseModel):
    status: Literal["ok"] = "ok"


class ReadinessResponse(BaseModel):
    status: Literal["ok"] = "ok"
    checks: dict[str, str] = Field(default_factory=dict)
