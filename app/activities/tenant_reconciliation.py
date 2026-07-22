"""
Tenant reconciliation activities — list/persist steps for
TenantReconciliationWorkflow. Retries reuse
app.activities.tenant_onboarding.share_credit_line and
.register_phone_number directly; no duplicated Meta API logic here.

Idempotency: list_* and fetch_waba_currency are read-only. mark_* are
single-row UPDATEs keyed on waba_id — retrying just re-applies the same
values.
"""

import logging

from temporalio import activity
from temporalio.exceptions import ApplicationError

from app.schemas.workflows.tenant_reconciliation import (
    MarkCreditSharedInput,
    MarkPhoneRegisteredInput,
    TenantNeedingAction,
)


logger = logging.getLogger(__name__)


@activity.defn
async def list_tenants_needing_credit_share() -> list[TenantNeedingAction]:
    """Active tenants whose Solution Partner credit line was never confirmed shared."""
    from app.core.database import AsyncSessionLocal
    from app.repositories.tenant_repo import TenantRepo

    async with AsyncSessionLocal() as session:
        repo = TenantRepo(session)
        tenants = await repo.list_needing_credit_share()
    # waba_id is guaranteed non-null here — list_needing_credit_share filters
    # on waba_id IS NOT NULL (no WABA means nothing to share credit with).
    return [
        TenantNeedingAction(waba_id=t.waba_id) for t in tenants if t.waba_id is not None
    ]


@activity.defn
async def list_tenants_needing_phone_registration() -> list[TenantNeedingAction]:
    """Active tenants whose phone number was chosen but never registered for Cloud API."""
    from app.core.database import AsyncSessionLocal
    from app.repositories.tenant_repo import TenantRepo

    async with AsyncSessionLocal() as session:
        repo = TenantRepo(session)
        tenants = await repo.list_needing_phone_registration()
    # waba_id is guaranteed non-null here — a PHONE_UNREGISTERED status is
    # only ever set alongside a waba_id in the same write (see
    # app.activities.tenant_onboarding.register_tenant).
    return [
        TenantNeedingAction(waba_id=t.waba_id, phone_number_id=t.phone_number_id)
        for t in tenants
        if t.waba_id is not None
    ]


@activity.defn
async def fetch_waba_currency(waba_id: str) -> str:
    """
    Look up a WABA's currency via the platform System User token.

    share_credit_line requires a currency, and by the time reconciliation
    runs the original Embedded Signup response is long gone — see
    app.clients.whatsapp.get_waba_info.
    """
    from app.clients.whatsapp import WhatsAppAPIError, get_waba_info

    try:
        info = await get_waba_info(waba_id)
    except WhatsAppAPIError as exc:
        raise ApplicationError(
            f"Failed to fetch WABA info for {waba_id}: {exc}",
            type="META_API_ERROR",
        ) from exc
    currency: str = info.get("currency", "")
    return currency


@activity.defn
async def mark_credit_shared(inp: MarkCreditSharedInput) -> None:
    """Persist a successful reconciliation retry of credit sharing."""
    from app.core.database import AsyncSessionLocal
    from app.repositories.tenant_repo import TenantRepo

    async with AsyncSessionLocal() as session:
        repo = TenantRepo(session)
        await repo.mark_credit_shared(
            waba_id=inp.waba_id, allocation_config_id=inp.allocation_config_id
        )
        await session.commit()
    logger.info("credit_share_reconciled", extra={"waba_id": inp.waba_id})


@activity.defn
async def mark_phone_registered(inp: MarkPhoneRegisteredInput) -> None:
    """Persist a successful reconciliation retry of phone number registration."""
    from app.core.database import AsyncSessionLocal
    from app.repositories.tenant_repo import TenantRepo

    async with AsyncSessionLocal() as session:
        repo = TenantRepo(session)
        await repo.mark_phone_registered(
            waba_id=inp.waba_id, two_step_pin_encrypted=inp.two_step_pin_encrypted
        )
        await session.commit()
    logger.info("phone_registration_reconciled", extra={"waba_id": inp.waba_id})
