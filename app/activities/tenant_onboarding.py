"""
Tenant onboarding activities.

Each wraps a call to app/clients/whatsapp.py, translating WhatsAppAPIError into
a Temporal ApplicationError. Ordering and flow decisions live in the workflow.
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
    """Choose which WABA to onboard (pure selection; supports multi-WABA flows)."""
    if not inp.waba_accounts:
        raise ValueError("select_primary_waba called with an empty list.")

    if inp.preferred_waba_id is not None:
        for waba in inp.waba_accounts:
            if waba.id == inp.preferred_waba_id:
                return waba
        logger.warning(
            "preferred_waba_id_not_found",
            extra={
                "preferred_waba_id": inp.preferred_waba_id,
                "available_ids": [w.id for w in inp.waba_accounts],
            },
        )

    if len(inp.waba_accounts) > 1:
        logger.warning(
            "ambiguous_multi_waba_selection",
            extra={
                "selected_id": inp.waba_accounts[0].id,
                "available_ids": [w.id for w in inp.waba_accounts],
            },
        )

    return inp.waba_accounts[0]


@activity.defn
async def assign_system_user(inp: AssignSystemUserInput) -> bool:
    """Grant the System User access to the tenant's WABA (prerequisite for share_credit_line)."""
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
    Register the number for Cloud API use; returns the encrypted two-step PIN
    (plaintext never leaves this activity). Falls back to the System User token
    when inp.user_token is None (reconciliation).
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
    """Share the platform's credit line; returns allocation_config_id, or None on failure (non-fatal)."""
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
    """Optional post-registration smoke test; skipped if no recipient, non-fatal on failure."""
    from app.core.settings import settings

    if not settings.whatsapp_test_recipient_number:
        return False

    from app.clients.whatsapp import WhatsAppAPIError, send_text_message

    try:
        await send_text_message(
            phone_number_id,
            settings.whatsapp_test_recipient_number,
            f"{settings.app_name}: this number is registered and ready to send messages.",
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
    Attach the WABA to the caller's existing tenant row and return the result.
    ApplicationError(TENANT_CONFLICT) if the WABA/number is already connected
    to a different tenant.
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
