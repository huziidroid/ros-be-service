"""
OTP-based (phone/WhatsApp) signup and login — one request/verify pair.
See app/services/auth.py for how a given phone number is routed to a
signup or a login without the client declaring which.
"""

from fastapi import APIRouter, Request, status

from app.api.dependencies import RedisDep, SessionDep
from app.api.rate_limit import limiter
from app.core.settings import settings
from app.schemas.auth import AuthResult
from app.schemas.auth.otp import OtpRequestBody, OtpRequestedData, OtpVerifyRequestBody
from app.schemas.response import APIResponse, ok
from app.services.auth import request_otp, verify_otp


router = APIRouter(prefix="/otp", tags=["Auth"])


@router.post(
    "/request",
    response_model=APIResponse[OtpRequestedData],
    status_code=status.HTTP_200_OK,
    summary="Send a signup or login verification code",
    description=(
        "Sends a WhatsApp OTP. An already-registered phone number gets a "
        "login code. A new one gets a signup code and requires "
        "business_name, first_name, and last_name — held pending in Redis "
        "until verify, nothing is written to the database yet."
    ),
)
@limiter.limit(settings.rate_limit_otp_request)
async def request(
    request: Request,  # noqa: ARG001 — required by slowapi's Limiter.limit
    body: OtpRequestBody,
    session: SessionDep,
    redis: RedisDep,
) -> APIResponse[OtpRequestedData]:
    data = await request_otp(session, redis, body)
    return ok(data=data, message="Verification code sent.")


@router.post(
    "/verify",
    response_model=APIResponse[AuthResult],
    status_code=status.HTTP_200_OK,
    summary="Verify a code and complete signup or login",
    description=(
        "Verifies the code. If it carried pending signup data, creates the "
        "Tenant and its owner User atomically; otherwise completes a login "
        "for the existing User. Either way, returns access + refresh tokens."
    ),
)
async def verify(
    body: OtpVerifyRequestBody, session: SessionDep, redis: RedisDep
) -> APIResponse[AuthResult]:
    data = await verify_otp(session, redis, body)
    return ok(data=data, message="Success.")
