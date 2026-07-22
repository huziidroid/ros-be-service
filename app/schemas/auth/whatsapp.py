"""
Pydantic schemas for the WhatsApp Embedded Signup callback (tenant onboarding).
"""

from enum import StrEnum

from pydantic import BaseModel, Field

from app.schemas.workflows import PhoneNumberStatus
from app.schemas.workflows.tenant_onboarding import OnboardingStatus


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
