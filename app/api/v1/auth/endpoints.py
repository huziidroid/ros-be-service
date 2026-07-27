"""
Auth endpoint handlers. Decorator-free — the HTTP metadata (path, method,
status, summary) lives in `router.py`, which registers these with
`add_api_route`. Cross-cutting behaviour that must wrap the handler (slowapi
rate limiting) stays here on the function.
"""

import logging

from fastapi import Request, Response

from app.api.dependencies import (
    CurrentUserDep,
    RedisDep,
    SessionDep,
    TemporalDep,
)
from app.core.rate_limit import limiter
from app.core.settings import settings
from app.schemas.auth import (
    AuthResult,
    EmailLoginRequestBody,
    EmailSignupRequestBody,
    EmbeddedSignupCallbackRequest,
    EmbeddedSignupOutcome,
    OtpRequestBody,
    OtpRequestedData,
    OtpVerifyRequestBody,
    RefreshRequestBody,
    RegisteredPhoneNumber,
    TenantOnboardingData,
    TokenPair,
    UserSummary,
)
from app.schemas.response import APIResponse, ok
from app.services.auth import (
    login_with_email,
    refresh_tokens,
    request_otp,
    signup_with_email,
    verify_otp,
)
from app.services.onboarding import run_tenant_onboarding


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# OTP (phone/WhatsApp) — one request/verify pair. See app/services/auth.py for
# how a phone number is routed to signup vs login without the client declaring.
# ---------------------------------------------------------------------------


@limiter.limit(settings.rate_limit_otp_request)
async def request(
    request: Request,  # noqa: ARG001 — required by slowapi's Limiter.limit
    response: Response,  # noqa: ARG001 — slowapi injects X-RateLimit-* headers here
    body: OtpRequestBody,
    session: SessionDep,
    redis: RedisDep,
) -> APIResponse[OtpRequestedData]:
    data = await request_otp(session, redis, body)
    return ok(data=data, message="Verification code sent.")


async def verify(
    body: OtpVerifyRequestBody, session: SessionDep, redis: RedisDep
) -> APIResponse[AuthResult]:
    data = await verify_otp(session, redis, body)
    return ok(data=data, message="Success.")


# ---------------------------------------------------------------------------
# Email + password
# ---------------------------------------------------------------------------


@limiter.limit(settings.rate_limit_email_signup)
async def signup(
    request: Request,  # noqa: ARG001 — required by slowapi's Limiter.limit
    response: Response,  # noqa: ARG001 — slowapi injects X-RateLimit-* headers here
    body: EmailSignupRequestBody,
    session: SessionDep,
) -> APIResponse[AuthResult]:
    data = await signup_with_email(session, body)
    return ok(data=data, message="Account created.", status_code=201)


@limiter.limit(settings.rate_limit_email_login)
async def login(
    request: Request,  # noqa: ARG001 — required by slowapi's Limiter.limit
    response: Response,  # noqa: ARG001 — slowapi injects X-RateLimit-* headers here
    body: EmailLoginRequestBody,
    session: SessionDep,
) -> APIResponse[AuthResult]:
    data = await login_with_email(session, body)
    return ok(data=data, message="Logged in.")


async def refresh(
    body: RefreshRequestBody, session: SessionDep
) -> APIResponse[TokenPair]:
    data = await refresh_tokens(session, body)
    return ok(data=data, message="Token refreshed.")


async def me(current_user: CurrentUserDep) -> APIResponse[UserSummary]:
    data = UserSummary(
        id=str(current_user.id),
        tenant_id=str(current_user.tenant_id),
        first_name=current_user.first_name,
        last_name=current_user.last_name,
        email=current_user.email,
        phone_number=current_user.phone_number,
    )
    return ok(data=data)


# ---------------------------------------------------------------------------
# WhatsApp Embedded Signup callback — the "connect WhatsApp" step.
# ---------------------------------------------------------------------------


async def embedded_signup_callback(
    body: EmbeddedSignupCallbackRequest,
    temporal: TemporalDep,
    current_user: CurrentUserDep,
) -> APIResponse[TenantOnboardingData]:
    """
    Authenticated, optional step performed after signup — not part of login.
    The tenant row already exists; the workflow attaches the WABA to it.

    Frontend POSTs the short-lived Embedded Signup `code` plus the
    WA_EMBEDDED_SIGNUP session event, with the distributor's own access token.
    If the event shows the flow didn't succeed (or there's no code), we log and
    return without calling Meta. Otherwise the onboarding service runs
    TenantOnboardingWorkflow synchronously — exchange the code, select the WABA,
    share the Solution Partner credit line, register the primary phone number,
    and attach the WABA to the caller's tenant — and we return the updated
    tenant summary.
    """
    if not body.code:
        logger.info(
            "embedded_signup_no_code",
            extra={"event": body.event, "current_step": body.current_step},
        )
        return ok(
            data=TenantOnboardingData(
                status=EmbeddedSignupOutcome.ERROR
                if body.error_code
                else EmbeddedSignupOutcome.CANCELLED
            ),
            message="Embedded Signup did not complete — no code to exchange.",
        )

    if not body.completed:
        # Meta sometimes issues a code even on non-success paths, but the
        # event says the customer didn't finish — don't burn a single-use
        # code on an abandoned or errored signup.
        logger.warning(
            "embedded_signup_not_successful",
            extra={
                "event": body.event,
                "current_step": body.current_step,
                "error_code": body.error_code,
                "error_message": body.error_message,
            },
        )
        outcome = (
            EmbeddedSignupOutcome.ERROR
            if (body.error_code or body.event == "ERROR")
            else EmbeddedSignupOutcome.CANCELLED
        )
        return ok(
            data=TenantOnboardingData(status=outcome),
            message="Embedded Signup was not completed successfully.",
        )

    # Temporal errors → typed AppError happens in the service; the global
    # handler turns those into the standard envelope.
    result = await run_tenant_onboarding(
        temporal,
        code=body.code,
        tenant_id=str(current_user.tenant_id),
        preferred_waba_id=body.waba_id,
    )

    return ok(
        data=TenantOnboardingData(
            status=EmbeddedSignupOutcome.REGISTERED,
            waba_id=result.waba_id,
            display_name=result.display_name,
            onboarding_status=result.onboarding_status,
            credit_shared=result.credit_shared,
            phone_numbers=[
                RegisteredPhoneNumber(
                    phone_number_id=pn.id,
                    display_phone_number=pn.display_phone_number,
                    verified_name=pn.verified_name,
                    status=pn.status,
                )
                for pn in result.phone_numbers
            ],
        ),
        message="Tenant registered successfully.",
    )
