"""
Shared workflow value types.

Types used across multiple workflows live here.
Workflow-specific inputs/outputs live in their own module:
  app.schemas.workflows.tenant_onboarding
  app.schemas.workflows.message_intake
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


@dataclass
class WABAInfo:
    """A single WhatsApp Business Account returned by Meta."""

    id: str
    name: str
    currency: str  # ISO-4217-3 code, e.g. "PKR" — required by share_credit_line


class PhoneNumberStatus(StrEnum):
    """
    Meta's own phone-number status vocabulary (Cloud API
    `phone_numbers[].status`) — not ours to define, so this only names the
    values Meta currently documents.

    UNKNOWN is a local fallback, never sent by Meta itself: _missing_ maps
    any value we don't recognize to it, so a status Meta adds later is
    stored/displayed as "unknown" instead of raising a hard validation
    error the moment it shows up in a real API response.
    """

    CONNECTED = "CONNECTED"
    DISCONNECTED = "DISCONNECTED"
    PENDING = "PENDING"
    RESTRICTED = "RESTRICTED"
    RATE_LIMITED = "RATE_LIMITED"
    FLAGGED = "FLAGGED"
    MIGRATED = "MIGRATED"
    UNVERIFIED = "UNVERIFIED"
    UNKNOWN = "UNKNOWN"

    @classmethod
    def _missing_(cls, value: object) -> PhoneNumberStatus:  # noqa: ARG003 — Enum's hook signature; any unrecognized value maps to UNKNOWN
        return cls.UNKNOWN


@dataclass
class PhoneNumberInfo:
    """A single phone number registered under a WABA."""

    id: str  # phone_number_id — webhook routing key
    display_phone_number: str  # human-readable e.g. +92 300 1234567
    verified_name: str
    status: PhoneNumberStatus


__all__ = ["WABAInfo", "PhoneNumberInfo", "PhoneNumberStatus"]
