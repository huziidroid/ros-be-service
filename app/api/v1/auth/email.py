"""
Email + password signup/login, token refresh, and the current-user lookup.
"""

from fastapi import APIRouter, Request, status

from app.api.dependencies import CurrentUserDep, SessionDep
from app.api.rate_limit import limiter
from app.core.settings import settings
from app.schemas.auth import AuthResult, TokenPair, UserSummary
from app.schemas.auth.email import (
    EmailLoginRequestBody,
    EmailSignupRequestBody,
    RefreshRequestBody,
)
from app.schemas.response import APIResponse, ok
from app.services.auth import login_with_email, refresh_tokens, signup_with_email


router = APIRouter(tags=["Auth"])


@router.post(
    "/signup",
    response_model=APIResponse[AuthResult],
    status_code=status.HTTP_201_CREATED,
    summary="Sign up with email + password",
)
@limiter.limit(settings.rate_limit_email_signup)
async def signup(
    request: Request,  # noqa: ARG001 — required by slowapi's Limiter.limit
    body: EmailSignupRequestBody,
    session: SessionDep,
) -> APIResponse[AuthResult]:
    data = await signup_with_email(session, body)
    return ok(data=data, message="Account created.", status_code=201)


@router.post(
    "/login",
    response_model=APIResponse[AuthResult],
    status_code=status.HTTP_200_OK,
    summary="Log in with email + password",
)
@limiter.limit(settings.rate_limit_email_login)
async def login(
    request: Request,  # noqa: ARG001 — required by slowapi's Limiter.limit
    body: EmailLoginRequestBody,
    session: SessionDep,
) -> APIResponse[AuthResult]:
    data = await login_with_email(session, body)
    return ok(data=data, message="Logged in.")


@router.post(
    "/refresh",
    response_model=APIResponse[TokenPair],
    status_code=status.HTTP_200_OK,
    summary="Exchange a refresh token for a new token pair",
)
async def refresh(
    body: RefreshRequestBody, session: SessionDep
) -> APIResponse[TokenPair]:
    data = await refresh_tokens(session, body)
    return ok(data=data, message="Token refreshed.")


@router.get(
    "/me",
    response_model=APIResponse[UserSummary],
    status_code=status.HTTP_200_OK,
    summary="Get the current authenticated user",
)
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
