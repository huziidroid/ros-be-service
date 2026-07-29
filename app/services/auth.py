"""
Auth service — orchestrates signup, login, and token refresh over two identity
methods (WhatsApp OTP and email + password), both converging on one Tenant+User
creation and token issuance. Writes run in a single transaction; duplicate
email/phone races surface as ConflictError.
"""

import logging
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.redis import RedisClient
from app.core.exceptions import ConflictError, UnauthorizedError, UnprocessableError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.core.settings import settings
from app.models.user import User
from app.repositories.tenant_repo import TenantRepo
from app.repositories.user_repo import UserRepo
from app.schemas.auth import (
    AuthResult,
    EmailLoginRequestBody,
    EmailSignupRequestBody,
    OtpRequestBody,
    OtpRequestedData,
    OtpVerifyRequestBody,
    PendingSignup,
    RefreshRequestBody,
    TokenError,
    TokenPair,
    UserSummary,
)
from app.services import otp


logger = logging.getLogger(__name__)


def _build_auth_result(user: User) -> AuthResult:
    return AuthResult(
        user=UserSummary(
            id=str(user.id),
            tenant_id=str(user.tenant_id),
            first_name=user.first_name,
            last_name=user.last_name,
            email=user.email,
            phone_number=user.phone_number,
        ),
        tokens=TokenPair(
            access_token=create_access_token(
                user_id=str(user.id), tenant_id=str(user.tenant_id)
            ),
            refresh_token=create_refresh_token(
                user_id=str(user.id), tenant_id=str(user.tenant_id)
            ),
        ),
    )


async def _create_tenant_and_owner(
    session: AsyncSession,
    *,
    business_name: str,
    first_name: str,
    last_name: str,
    email: str | None = None,
    phone_number: str | None = None,
    password_hash: str | None = None,
) -> User:
    """Create a Tenant + owner User in one transaction; ConflictError on a duplicate race."""
    try:
        tenant = await TenantRepo(session).create_pending(display_name=business_name)
        user = await UserRepo(session).create(
            tenant_id=tenant.id,
            first_name=first_name,
            last_name=last_name,
            email=email,
            phone_number=phone_number,
            password_hash=password_hash,
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ConflictError(
            "An account with this email or phone number already exists.",
            internal_detail=str(exc),
        ) from exc
    return user


# --- OTP: one request/verify pair covering both signup and login ---


async def request_otp(
    session: AsyncSession, redis: RedisClient, body: OtpRequestBody
) -> OtpRequestedData:
    """Send a WhatsApp OTP; a registered number gets a login code, a new one a signup code."""
    existing = await UserRepo(session).get_by_phone_number(body.phone_number)

    pending = None
    if existing is None:
        if not (body.business_name and body.first_name and body.last_name):
            raise UnprocessableError(
                "No account found for this number. To sign up, include "
                "business_name, first_name, and last_name."
            )
        pending = PendingSignup(
            business_name=body.business_name,
            first_name=body.first_name,
            last_name=body.last_name,
        )

    await otp.request_otp(redis, phone_number=body.phone_number, pending=pending)
    return OtpRequestedData(
        phone_number=body.phone_number,
        expires_in_seconds=settings.otp_expire_seconds,
    )


async def verify_otp(
    session: AsyncSession, redis: RedisClient, body: OtpVerifyRequestBody
) -> AuthResult:
    """Verify a code; pending signup data creates the Tenant+User, else completes a login."""
    pending = await otp.verify_otp(
        redis, phone_number=body.phone_number, code=body.code
    )

    if pending is not None:
        user = await _create_tenant_and_owner(
            session,
            business_name=pending.business_name,
            first_name=pending.first_name,
            last_name=pending.last_name,
            phone_number=body.phone_number,
        )
        logger.info("signup_otp_completed", extra={"user_id": str(user.id)})
        return _build_auth_result(user)

    login_user = await UserRepo(session).get_by_phone_number(body.phone_number)
    if login_user is None:
        # Account deleted/deactivated between OTP request and verify.
        raise UnprocessableError("No account found for this number.")
    logger.info("login_otp_completed", extra={"user_id": str(login_user.id)})
    return _build_auth_result(login_user)


# --- Email + password ---


async def signup_with_email(
    session: AsyncSession, body: EmailSignupRequestBody
) -> AuthResult:
    existing = await UserRepo(session).get_by_email(body.email)
    if existing is not None:
        raise ConflictError(
            "An account with this email already exists. Try logging in instead."
        )

    user = await _create_tenant_and_owner(
        session,
        business_name=body.business_name,
        first_name=body.first_name,
        last_name=body.last_name,
        email=body.email,
        password_hash=hash_password(body.password),
    )
    logger.info("signup_email_completed", extra={"user_id": str(user.id)})
    return _build_auth_result(user)


async def login_with_email(
    session: AsyncSession, body: EmailLoginRequestBody
) -> AuthResult:
    user = await UserRepo(session).get_by_email(body.email)
    # Same error for unknown user and wrong password — don't leak which emails exist.
    if (
        user is None
        or user.password_hash is None
        or not verify_password(body.password, user.password_hash)
    ):
        raise UnauthorizedError("Invalid email or password.")

    logger.info("login_email_completed", extra={"user_id": str(user.id)})
    return _build_auth_result(user)


# --- Token refresh ---


async def refresh_tokens(session: AsyncSession, body: RefreshRequestBody) -> TokenPair:
    try:
        payload = decode_token(body.refresh_token, expected_type="refresh")
    except TokenError as exc:
        raise UnauthorizedError("Invalid or expired refresh token.") from exc

    user = await UserRepo(session).get_by_id(UUID(payload.user_id))
    if user is None:
        raise UnauthorizedError("Invalid or expired refresh token.")

    return TokenPair(
        access_token=create_access_token(
            user_id=str(user.id), tenant_id=str(user.tenant_id)
        ),
        refresh_token=create_refresh_token(
            user_id=str(user.id), tenant_id=str(user.tenant_id)
        ),
    )
