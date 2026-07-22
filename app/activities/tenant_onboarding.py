"""
Tenant onboarding activities.

Each activity wraps a call to app/clients/whatsapp.py, translates
WhatsAppAPIError into a Temporal ApplicationError, and returns a typed
result. Ordering and flow decisions stay in the workflow.

Idempotency:
- exchange_code: not retried (RetryPolicy(maximum_attempts=1)) — Meta codes
  are single-use. Workflow ID = tenant-onboarding-{code} prevents re-runs.
- subscribe_waba_webhook: safe to retry — duplicate subscriptions are no-ops.
- fetch_*: read-only, naturally idempotent.
- register_phone_number: safe to retry — each attempt sets a new PIN, so the
  number ends up with whichever PIN the last successful attempt used.
- share_credit_line: safe to retry; non-fatal in the workflow, so
  allocation_config_id just stays unset until retried out-of-band.
- register_tenant: updates the caller's tenant row by tenant_id (not an
  upsert — the row already exists from signup), naturally idempotent for
  retries of the same tenant_id/waba_id pair.
"""

import logging

from temporalio import activity
from temporalio.exceptions import ApplicationError

from app.schemas.workflows import PhoneNumberInfo, PhoneNumberStatus, WABAInfo
from app.schemas.workflows.tenant_onboarding import (
    AssignSystemUserInput,
    FetchPhoneNumbersInput,
    RegisterPhoneNumberInput,
    RegisterTenantInput,
    SelectPrimaryWabaInput,
    ShareCreditLineInput,
    SubscribeWebhookInput,
    TenantOnboardingResult,
)


logger = logging.getLogger(__name__)


@activity.defn
async def exchange_code(code: str) -> str:
    """Exchange the Embedded Signup code for a user access token."""
    from app.clients.whatsapp import WhatsAppAPIError, exchange_code_for_token

    try:
        return await exchange_code_for_token(code)
    except WhatsAppAPIError as exc:
        raise ApplicationError(
            f"Meta rejected code exchange: {exc}",
            type="META_API_ERROR",
            non_retryable=True,  # spent code — retrying will always fail
        ) from exc


@activity.defn
async def fetch_waba_accounts(user_token: str) -> list[WABAInfo]:
    """List all WABAs accessible with the given user token."""
    from app.clients.whatsapp import WhatsAppAPIError, get_waba_accounts

    try:
        raw = await get_waba_accounts(user_token)
    except WhatsAppAPIError as exc:
        raise ApplicationError(
            f"Failed to fetch WABA accounts: {exc}",
            type="META_API_ERROR",
        ) from exc
    return [
        WABAInfo(
            id=w["id"], name=w.get("name", w["id"]), currency=w.get("currency", "")
        )
        for w in raw
    ]


@activity.defn
async def select_primary_waba(inp: SelectPrimaryWabaInput) -> WABAInfo:
    """
    Choose which WABA to onboard — pure selection, no I/O (see
    app.domain.onboarding). Embedded Signup v4 supports multi-WABA flows, so
    this can't be a blind [0].
    """
    from app.domain.onboarding import select_primary_waba as _select

    return _select(inp.waba_accounts, inp.preferred_waba_id)


@activity.defn
async def assign_system_user(inp: AssignSystemUserInput) -> bool:
    """
    Grant the platform System User access to the tenant's WABA, using the
    short-lived Embedded Signup token. Also a prerequisite for
    share_credit_line — Meta requires System User access before a credit
    line can be shared.
    """
    from app.clients.whatsapp import WhatsAppAPIError
    from app.clients.whatsapp import assign_system_user as _assign

    try:
        return await _assign(inp.waba_id, inp.user_token)
    except WhatsAppAPIError as exc:
        raise ApplicationError(
            f"Failed to assign system user to WABA {inp.waba_id}: {exc}",
            type="META_API_ERROR",
        ) from exc


@activity.defn
async def subscribe_waba_webhook(inp: SubscribeWebhookInput) -> bool:
    """Subscribe this Meta App's webhook to the given WABA."""
    from app.clients.whatsapp import WhatsAppAPIError, subscribe_webhook

    try:
        return await subscribe_webhook(inp.waba_id, inp.user_token)
    except WhatsAppAPIError as exc:
        raise ApplicationError(
            f"Failed to subscribe webhook for WABA {inp.waba_id}: {exc}",
            type="META_API_ERROR",
        ) from exc


@activity.defn
async def fetch_phone_numbers(inp: FetchPhoneNumbersInput) -> list[PhoneNumberInfo]:
    """Fetch all phone numbers registered under a WABA."""
    from app.clients.whatsapp import WhatsAppAPIError, get_phone_numbers

    try:
        raw = await get_phone_numbers(inp.waba_id, inp.user_token)
    except WhatsAppAPIError as exc:
        raise ApplicationError(
            f"Failed to fetch phone numbers for WABA {inp.waba_id}: {exc}",
            type="META_API_ERROR",
        ) from exc
    return [
        PhoneNumberInfo(
            id=pn["id"],
            display_phone_number=pn.get("display_phone_number", ""),
            verified_name=pn.get("verified_name", ""),
            status=PhoneNumberStatus(pn.get("status", "UNKNOWN")),
        )
        for pn in raw
    ]


@activity.defn
async def register_phone_number(inp: RegisterPhoneNumberInput) -> str:
    """
    Register the tenant's phone number for Cloud API use.

    Generates a fresh two-step PIN, registers it with Meta, then encrypts it
    before returning — the plaintext PIN never leaves this activity or lands
    in Temporal's workflow history.

    Falls back to the platform System User token when inp.user_token is
    None (reconciliation calls this without one — see
    app.workflows.tenant_reconciliation). Meta's Register API accepts a
    System User token with whatsapp_business_management +
    whatsapp_business_messaging permissions.
    """
    from app.clients.whatsapp import WhatsAppAPIError
    from app.clients.whatsapp import register_phone_number as _register
    from app.core.security import encrypt_secret, generate_numeric_code
    from app.core.settings import settings

    token = inp.user_token or settings.whatsapp_system_user_token.get_secret_value()
    pin = generate_numeric_code(6)
    try:
        await _register(inp.phone_number_id, token, pin)
    except WhatsAppAPIError as exc:
        raise ApplicationError(
            f"Failed to register phone number {inp.phone_number_id}: {exc}",
            type="META_API_ERROR",
        ) from exc
    return encrypt_secret(pin)


@activity.defn
async def share_credit_line(inp: ShareCreditLineInput) -> str | None:
    """
    Share Retail OS's extended credit line with the tenant's WABA.

    Returns allocation_config_id on success, or None if the call failed
    (logged, not raised — this step is non-fatal).
    """
    from app.clients.whatsapp import WhatsAppAPIError
    from app.clients.whatsapp import share_credit_line as _share

    try:
        result = await _share(inp.waba_id, inp.waba_currency)
    except WhatsAppAPIError as exc:
        logger.warning(
            "credit_line_share_failed",
            extra={"waba_id": inp.waba_id, "error": str(exc)},
        )
        return None
    return result.get("allocation_config_id")


@activity.defn
async def send_test_message(phone_number_id: str) -> bool:
    """
    Optional post-registration smoke test — sends a short text from the
    newly registered number to settings.whatsapp_test_recipient_number.

    Skipped if no recipient is configured. Non-fatal on failure: a brand
    new number has no open 24-hour customer-service window yet, so a
    failed send here doesn't indicate a broken registration.
    """
    from app.core.settings import settings

    if not settings.whatsapp_test_recipient_number:
        return False

    from app.clients.whatsapp import WhatsAppAPIError, send_text_message

    try:
        await send_text_message(
            phone_number_id,
            settings.whatsapp_test_recipient_number,
            "Retail OS: this number is registered and ready to send messages.",
        )
    except WhatsAppAPIError as exc:
        logger.warning(
            "test_message_failed",
            extra={"phone_number_id": phone_number_id, "error": str(exc)},
        )
        return False
    return True


@activity.defn
async def register_tenant(inp: RegisterTenantInput) -> TenantOnboardingResult:
    """
    Attach the WABA to the caller's existing tenant row (created at signup)
    and return the result.

    Raises ApplicationError(type="TENANT_CONFLICT") if the WABA or phone
    number is already connected to a different tenant — TenantRepo.attach_waba
    pre-checks both and also guards the concurrent-request race, so this
    never leaks a raw IntegrityError to the workflow caller.
    """
    from uuid import UUID

    from app.core.database import AsyncSessionLocal
    from app.core.exceptions import ConflictError
    from app.repositories.tenant_repo import TenantRepo

    async with AsyncSessionLocal() as session:
        repo = TenantRepo(session)
        try:
            await repo.attach_waba(
                tenant_id=UUID(inp.tenant_id),
                waba_id=inp.waba_id,
                display_name=inp.display_name,
                onboarding_status=inp.onboarding_status,
                phone_number_id=inp.phone_number_id,
                phone_number=inp.phone_number,
                two_step_pin_encrypted=inp.two_step_pin_encrypted,
                allocation_config_id=inp.allocation_config_id,
            )
        except ConflictError as exc:
            await session.rollback()
            raise ApplicationError(
                exc.message, type="TENANT_CONFLICT", non_retryable=True
            ) from exc
        await session.commit()

    logger.info(
        "tenant_registered",
        extra={
            "waba_id": inp.waba_id,
            "display_name": inp.display_name,
            "phone_number_id": inp.phone_number_id,
            "onboarding_status": inp.onboarding_status,
            "credit_shared": inp.allocation_config_id is not None,
        },
    )

    return TenantOnboardingResult(
        waba_id=inp.waba_id,
        display_name=inp.display_name,
        onboarding_status=inp.onboarding_status,
        phone_numbers=inp.all_phone_numbers,
        credit_shared=inp.allocation_config_id is not None,
    )
