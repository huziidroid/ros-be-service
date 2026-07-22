from fastapi import APIRouter

from app.api.v1.auth.email import router as email_auth_router
from app.api.v1.auth.otp import router as otp_auth_router
from app.api.v1.auth.whatsapp import router as whatsapp_auth_router


auth_router = APIRouter(
    prefix="/auth",
)
auth_router.include_router(otp_auth_router)
auth_router.include_router(email_auth_router)
auth_router.include_router(whatsapp_auth_router)
