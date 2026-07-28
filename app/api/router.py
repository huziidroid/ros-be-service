from fastapi import APIRouter

from app.api.v1.auth.router import auth_router
from app.api.v1.health.router import router as health_router
from app.api.v1.webhooks.router import router as webhook_router


api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health_router)
api_router.include_router(webhook_router)
api_router.include_router(auth_router)
