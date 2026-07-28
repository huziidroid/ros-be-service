"""
Schemas for TenantReconciliationWorkflow and its activities.

Retries the two TenantOnboardingWorkflow steps allowed to fail non-fatally:
credit sharing and phone registration. See app.workflows.tenant_reconciliation.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TenantNeedingAction:
    """One tenant found by a list_needing_* query — just enough to retry."""

    waba_id: str
    phone_number_id: str | None = None


@dataclass
class MarkCreditSharedInput:
    waba_id: str
    allocation_config_id: str


@dataclass
class MarkPhoneRegisteredInput:
    waba_id: str
    two_step_pin_encrypted: str


@dataclass
class TenantReconciliationResult:
    """Summary of one reconciliation pass — for logging/observability only."""

    credit_shares_attempted: int = 0
    credit_shares_succeeded: int = 0
    phone_registrations_attempted: int = 0
    phone_registrations_succeeded: int = 0


__all__ = [
    "TenantNeedingAction",
    "MarkCreditSharedInput",
    "MarkPhoneRegisteredInput",
    "TenantReconciliationResult",
]
