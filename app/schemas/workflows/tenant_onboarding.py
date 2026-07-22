"""
Schemas for TenantOnboardingWorkflow and its activities.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from app.schemas.workflows import PhoneNumberInfo, WABAInfo


# ---------------------------------------------------------------------------
# Onboarding status — what state a tenant ended up in after the workflow ran
# ---------------------------------------------------------------------------
#
# Backs Tenant.onboarding_status as a native Postgres enum (see
# app/models/tenant.py, migration 0004) — fully ours, every value is set by
# our own code, so no external-vocabulary fallback is needed here (contrast
# PhoneNumberStatus / MessageDeliveryStatus below and in
# app/schemas/webhooks/whatsapp.py, which come from Meta).


class OnboardingStatus(StrEnum):
    NOT_CONNECTED = "not_connected"
    """Account created via signup; no WABA connected yet."""

    COMPLETE = "complete"
    """Phone number selected and registered for Cloud API use."""

    WABA_ONLY = "waba_only"
    """FINISH_ONLY_WABA — WABA connected, no phone number chosen."""

    PHONE_UNREGISTERED = "phone_unregistered"
    """Phone number chosen, but the Cloud API register call failed."""


@dataclass
class TenantOnboardingInput:
    """Input to TenantOnboardingWorkflow."""

    code: str
    """Short-lived code received from Meta after Embedded Signup."""

    tenant_id: str
    """
    The authenticated caller's tenant (see app/api/v1/auth/whatsapp.py) —
    WhatsApp connect is an authenticated, optional step performed after
    signup, so the tenant row already exists. register_tenant attaches the
    WABA to this row instead of creating a new one.
    """

    preferred_waba_id: str | None = None
    """
    WABA ID from the frontend's WA_EMBEDDED_SIGNUP session event, if sent —
    disambiguates multi-WABA flows instead of taking the first WABA returned.
    """


@dataclass
class TenantOnboardingResult:
    """Output of TenantOnboardingWorkflow — returned to the auth endpoint."""

    waba_id: str
    display_name: str
    onboarding_status: OnboardingStatus
    phone_numbers: list[PhoneNumberInfo] = field(default_factory=list)
    credit_shared: bool = False


# ---------------------------------------------------------------------------
# Activity-level inputs (multi-param activities use a dataclass)
# ---------------------------------------------------------------------------


@dataclass
class SubscribeWebhookInput:
    waba_id: str
    user_token: str


@dataclass
class FetchPhoneNumbersInput:
    waba_id: str
    user_token: str


@dataclass
class AssignSystemUserInput:
    waba_id: str
    user_token: (
        str  # short-lived token from Embedded Signup — used once, then discarded
    )


@dataclass
class SelectPrimaryWabaInput:
    waba_accounts: list[WABAInfo]
    preferred_waba_id: str | None = None


@dataclass
class RegisterPhoneNumberInput:
    phone_number_id: str
    user_token: str | None = None
    """
    Embedded Signup's short-lived token, when called during onboarding. Left
    None from reconciliation — the activity falls back to the platform
    System User token, which already has durable WABA access.
    """


@dataclass
class ShareCreditLineInput:
    waba_id: str
    waba_currency: str


@dataclass
class RegisterTenantInput:
    tenant_id: str
    """Existing tenant row (created at signup) to attach this WABA to."""

    waba_id: str
    display_name: str
    onboarding_status: OnboardingStatus
    phone_number_id: str | None = None  # primary phone number id
    phone_number: str | None = None  # human-readable primary number
    all_phone_numbers: list[PhoneNumberInfo] = field(default_factory=list)
    two_step_pin_encrypted: str | None = None
    allocation_config_id: str | None = None


__all__ = [
    "OnboardingStatus",
    "TenantOnboardingInput",
    "TenantOnboardingResult",
    "SubscribeWebhookInput",
    "FetchPhoneNumbersInput",
    "AssignSystemUserInput",
    "SelectPrimaryWabaInput",
    "RegisterPhoneNumberInput",
    "ShareCreditLineInput",
    "RegisterTenantInput",
]
