"""
Auth schemas: the shared token/user types returned by every signup/login
endpoint, plus the request/response bodies for email, OTP (phone/WhatsApp),
and the WhatsApp Embedded Signup callback.
"""

import re
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator

from app.schemas.workflows import PhoneNumberStatus
from app.schemas.workflows.tenant_onboarding import OnboardingStatus


# ---------------------------------------------------------------------------
# Shared — returned by every signup/login endpoint
# ---------------------------------------------------------------------------


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserSummary(BaseModel):
    id: str
    tenant_id: str
    first_name: str
    last_name: str
    email: str | None = None
    phone_number: str | None = None


class AuthResult(BaseModel):
    """Returned by every signup/login endpoint."""

    user: UserSummary
    tokens: TokenPair


# ---------------------------------------------------------------------------
# Email + password
# ---------------------------------------------------------------------------

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_MIN_PASSWORD_LENGTH = 8


def _validate_email(value: str) -> str:
    if not _EMAIL.match(value):
        raise ValueError("email is not a valid email address.")
    return value.lower()


def _validate_password(value: str) -> str:
    if len(value) < _MIN_PASSWORD_LENGTH:
        raise ValueError(
            f"password must be at least {_MIN_PASSWORD_LENGTH} characters."
        )
    return value


class EmailSignupRequestBody(BaseModel):
    business_name: str
    first_name: str
    last_name: str
    email: str
    password: str

    _validate_email = field_validator("email")(_validate_email)
    _validate_password = field_validator("password")(_validate_password)


class EmailLoginRequestBody(BaseModel):
    email: str
    password: str

    _validate_email = field_validator("email")(_validate_email)


class RefreshRequestBody(BaseModel):
    refresh_token: str


# ---------------------------------------------------------------------------
# OTP (phone/WhatsApp) — one request/verify pair. Whether a number is signing
# up or logging in is decided by whether it's already registered (see
# app/services/auth.py), so the name fields are only required first time.
# ---------------------------------------------------------------------------

_E164 = re.compile(r"^\+[1-9]\d{6,14}$")


def _validate_phone_number(value: str) -> str:
    if not _E164.match(value):
        raise ValueError("phone_number must be in E.164 format, e.g. +923001234567.")
    return value


class OtpRequestBody(BaseModel):
    phone_number: str
    # Only required when phone_number isn't registered yet — see
    # app.services.auth.request_otp for the missing-field error.
    business_name: str | None = None
    first_name: str | None = None
    last_name: str | None = None

    _validate_phone_number = field_validator("phone_number")(_validate_phone_number)


class OtpVerifyRequestBody(BaseModel):
    phone_number: str
    code: str

    _validate_phone_number = field_validator("phone_number")(_validate_phone_number)


class OtpRequestedData(BaseModel):
    phone_number: str
    expires_in_seconds: int


# ---------------------------------------------------------------------------
# WhatsApp Embedded Signup callback (tenant onboarding)
# ---------------------------------------------------------------------------

# Event values meaning Embedded Signup genuinely completed — anything else
# (CANCEL, ERROR, unrecognized) means the customer didn't finish. See
# https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/implementation#session-logging-message-event-listener
_SUCCESS_EVENTS = frozenset(
    {
        "FINISH",
        "FINISH_ONLY_WABA",
        "FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING",
        "FINISH_OBO_MIGRATION",
        "FINISH_GRANT_ONLY_API_ACCESS",
    }
)


class EmbeddedSignupOutcome(StrEnum):
    """TenantOnboardingData.status — the outcome of one Embedded Signup callback."""

    REGISTERED = "registered"
    CANCELLED = "cancelled"
    ERROR = "error"


class EmbeddedSignupCallbackRequest(BaseModel):
    """
    Body posted by the frontend after Embedded Signup finishes.

    Embedded Signup reports outcomes on two channels: the FB.login callback
    (`code`) and a WA_EMBEDDED_SIGNUP window message event (`event` + the
    rest of these fields) — forward whatever was captured from both. `code`
    is the only required field; without `event` we can't tell a genuine
    FINISH from a CANCEL/ERROR the customer already saw.

    See https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/implementation
    """

    code: str | None = None
    """Short-lived (30s) exchangeable code. Present on successful completion."""

    event: str | None = None
    """
    FINISH | FINISH_ONLY_WABA | FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING |
    FINISH_OBO_MIGRATION | FINISH_GRANT_ONLY_API_ACCESS | ERROR | CANCEL
    """

    waba_id: str | None = None
    phone_number_id: str | None = None
    business_id: str | None = None
    waba_ids: list[str] | None = None
    """Populated instead of waba_id for multi-WABA flows."""

    current_step: str | None = None
    """Set when event == CANCEL and the customer abandoned the flow."""

    error_code: str | None = None
    error_message: str | None = None
    """Set when the customer reported an error from within the flow."""

    @property
    def completed(self) -> bool:
        """
        True when the session event indicates Embedded Signup finished — or
        when no event was captured (we can't prove failure, so proceed and let
        the code exchange be the arbiter).
        """
        return self.event is None or self.event in _SUCCESS_EVENTS


class RegisteredPhoneNumber(BaseModel):
    phone_number_id: str
    display_phone_number: str
    verified_name: str
    status: PhoneNumberStatus


class TenantOnboardingData(BaseModel):
    """Data payload returned after an Embedded Signup callback."""

    status: EmbeddedSignupOutcome
    """Whether a tenant was actually onboarded."""

    waba_id: str | None = None
    display_name: str | None = None
    onboarding_status: OnboardingStatus | None = None
    """Set only when status == EmbeddedSignupOutcome.REGISTERED."""
    credit_shared: bool = False
    phone_numbers: list[RegisteredPhoneNumber] = Field(default_factory=list)
