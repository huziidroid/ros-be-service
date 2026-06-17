from fastapi import APIRouter

from app.schemas.health import HealthCheckResponse


router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", response_model=HealthCheckResponse)
async def live() -> HealthCheckResponse:
    return HealthCheckResponse(status="ok")
