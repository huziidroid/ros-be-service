from fastapi import APIRouter

from app.api.v1.health import router as health_router
from app.api.v1.webhook import router as webhook_router


api_router = APIRouter(prefix="/api/v1", tags=["api"])
api_router.include_router(health_router)
api_router.include_router(webhook_router)
