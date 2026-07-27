"""Schemas for TenantOnboardingWorkflow and its activities."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from app.schemas.workflows import PhoneNumberInfo, WABAInfo


# --- Onboarding status: backs Tenant.onboarding_status (native Postgres enum) ---


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
    """The authenticated caller's tenant (already exists) to attach the WABA to."""

    preferred_waba_id: str | None = None
    """WABA ID from the session event; disambiguates multi-WABA flows."""


@dataclass
class TenantOnboardingResult:
    """Output of TenantOnboardingWorkflow — returned to the auth endpoint."""

    waba_id: str
    display_name: str
    onboarding_status: OnboardingStatus
    phone_numbers: list[PhoneNumberInfo] = field(default_factory=list)
    credit_shared: bool = False


# --- Activity-level inputs (multi-param activities use a dataclass) ---


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
    user_token: str  # short-lived Embedded Signup token, used once


@dataclass
class SelectPrimaryWabaInput:
    waba_accounts: list[WABAInfo]
    preferred_waba_id: str | None = None


@dataclass
class RegisterPhoneNumberInput:
    phone_number_id: str
    user_token: str | None = None
    """Embedded Signup token; None from reconciliation (falls back to System User)."""


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
