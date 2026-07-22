"""
Auth service — orchestrates signup, login, and token refresh.

Two independent ways to prove identity: OTP over WhatsApp, or email +
password. Both converge on the same Tenant+User creation and token
issuance, so that part lives once here rather than duplicated per method.

OTP has a single request/verify pair for both signup and login — whether a
phone number is signing up or logging in is decided here (by whether
UserRepo already has that number), not by which endpoint the client calls.
See app.services.otp for the underlying Redis-backed code generation/
storage/delivery, imported qualified below to keep that distinction
visible: otp.request_otp/otp.verify_otp are the low-level primitives;
request_otp/verify_otp in this module are what the router actually calls.

Every write here happens inside one DB transaction (create_pending +
UserRepo.create share the same AsyncSession, committed together) — either
both the Tenant and its owner User exist, or neither does. Concurrent
signups for the same phone/email are caught by the DB's unique constraint
(migration 0003) and translated to a clean ConflictError instead of a raw
IntegrityError.
"""

import logging
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.redis import RedisClient
from app.core.exceptions import ConflictError, UnauthorizedError, UnprocessableError
from app.core.security import (
    TokenError,
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
from app.schemas.auth import AuthResult, TokenPair, UserSummary
from app.schemas.auth.email import (
    EmailLoginRequestBody,
    EmailSignupRequestBody,
    RefreshRequestBody,
)
from app.schemas.auth.otp import OtpRequestBody, OtpRequestedData, OtpVerifyRequestBody
from app.services import otp
from app.services.otp import PendingSignup


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
    """
    Create a Tenant + its owner User in one transaction.

    Raises ConflictError if a concurrent request already claimed the same
    email/phone_number (race between the caller's pre-check and this write).
    """
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


# ---------------------------------------------------------------------------
# OTP — one request/verify pair covering both signup and login
# ---------------------------------------------------------------------------


async def request_otp(
    session: AsyncSession, redis: RedisClient, body: OtpRequestBody
) -> OtpRequestedData:
    """
    Send a WhatsApp OTP. A registered phone number gets a login code; an
    unregistered one gets a signup code — the caller doesn't declare which,
    it's decided by whether UserRepo already knows this number.
    """
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
    """
    Verify a code. Pending signup data attached to it means this number was
    new at request time, so a Tenant + owner User get created now;
    otherwise this completes a login for an existing User.
    """
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
        # Account was deleted/deactivated between OTP request and verify.
        raise UnprocessableError("No account found for this number.")
    logger.info("login_otp_completed", extra={"user_id": str(login_user.id)})
    return _build_auth_result(login_user)


# ---------------------------------------------------------------------------
# Email + password
# ---------------------------------------------------------------------------


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
    # Same error for "no such user" and "wrong password" — don't help an
    # attacker enumerate registered emails.
    if (
        user is None
        or user.password_hash is None
        or not verify_password(body.password, user.password_hash)
    ):
        raise UnauthorizedError("Invalid email or password.")

    logger.info("login_email_completed", extra={"user_id": str(user.id)})
    return _build_auth_result(user)


# ---------------------------------------------------------------------------
# Token refresh
# ---------------------------------------------------------------------------


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
