"""
Meta WhatsApp Cloud API client — all outbound calls to the Meta Graph API:
  - Embedded Signup: exchange code → user access token
  - Assign platform System User to a tenant WABA (grants permanent access)
  - Fetch WABA accounts and phone numbers for a user token
  - Fetch a WABA's info via the System User token (reconciliation)
  - Subscribe this app's webhook to a WABA
  - Register a tenant's phone number for Cloud API use
  - Share Retail OS's extended credit line with a tenant's WABA
  - Send messages (text, template, interactive) on behalf of a tenant

Sending messages uses settings.whatsapp_system_user_token — a non-expiring
platform token valid across all tenant WABAs; callers never pass their own.

Non-2xx responses raise WhatsAppAPIError with the raw Meta error body;
callers translate it to a domain error.
"""

import logging
from typing import Any

import httpx

from app.core.settings import settings


logger = logging.getLogger(__name__)


class WhatsAppAPIError(Exception):
    """Raised when Meta Graph API returns a non-2xx response."""

    def __init__(self, status_code: int, body: dict[str, Any]) -> None:
        self.status_code = status_code
        self.body = body
        error = body.get("error", {})
        super().__init__(
            f"Meta API error {status_code}: "
            f"[{error.get('code')}] {error.get('message', body)}"
        )


def _build_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=settings.whatsapp_api_base,
        timeout=httpx.Timeout(30.0),
        headers={"Accept": "application/json"},
    )


def _raise_for_status(response: httpx.Response) -> dict[str, Any]:
    body: dict[str, Any] = response.json()
    if response.is_error:
        # Log only the path, never the full URL — query strings can carry
        # access_token/client_secret.
        error = body.get("error", {}) if isinstance(body, dict) else {}
        logger.error(
            "meta_api_error",
            extra={
                "status": response.status_code,
                "path": response.url.path,
                "meta_error_code": error.get("code"),
                "meta_error_message": error.get("message"),
            },
        )
        raise WhatsAppAPIError(response.status_code, body)
    return body


# ---------------------------------------------------------------------------
# Embedded Signup — code exchange
# ---------------------------------------------------------------------------


async def exchange_code_for_token(code: str) -> str:
    """
    Exchange a short-lived Embedded Signup code for a user access token.

    Meta endpoint:
      GET /oauth/access_token
        ?client_id=APP_ID
        &client_secret=APP_SECRET
        &code=CODE

    Returns the access_token string.
    """
    async with _build_client() as client:
        response = await client.get(
            "/oauth/access_token",
            params={
                "client_id": settings.whatsapp_app_id,
                "client_secret": settings.whatsapp_app_secret.get_secret_value(),
                "code": code,
            },
        )
    data = _raise_for_status(response)
    token: str = data["access_token"]
    logger.info("embedded_signup_token_exchanged")
    return token


# ---------------------------------------------------------------------------
# WABA and phone number discovery
# ---------------------------------------------------------------------------


async def get_waba_accounts(user_token: str) -> list[dict[str, Any]]:
    """
    List WhatsApp Business Accounts accessible with the given user token.

    Meta endpoint:
      GET /me/whatsapp_business_accounts   (token via Authorization header)

    Returns list of {id, name, ...} dicts.
    """
    async with _build_client() as client:
        response = await client.get(
            "/me/whatsapp_business_accounts",
            params={"fields": "id,name,currency,timezone_id"},
            headers={"Authorization": f"Bearer {user_token}"},
        )
    data = _raise_for_status(response)
    accounts: list[dict[str, Any]] = data.get("data", [])
    logger.info("waba_accounts_fetched", extra={"count": len(accounts)})
    return accounts


async def get_waba_info(waba_id: str) -> dict[str, Any]:
    """
    Fetch a single WABA's info using the platform System User token.

    Used by reconciliation, where the tenant's short-lived Embedded Signup
    token is long gone — the System User already has MANAGE access (granted
    during onboarding's assign_system_user step), so no per-tenant token
    is needed.

    Meta endpoint:
      GET /{waba_id}?fields=id,name,currency
        Authorization: Bearer SYSTEM_USER_TOKEN

    Returns {id, name, currency}.
    """
    async with _build_client() as client:
        response = await client.get(
            f"/{waba_id}",
            params={"fields": "id,name,currency"},
            headers={
                "Authorization": f"Bearer {settings.whatsapp_system_user_token.get_secret_value()}"
            },
        )
    return _raise_for_status(response)


async def get_phone_numbers(waba_id: str, user_token: str) -> list[dict[str, Any]]:
    """
    List phone numbers registered under a WABA.

    Meta endpoint:
      GET /{waba_id}/phone_numbers   (token via Authorization header)
        &fields=id,display_phone_number,verified_name,status

    Returns list of {id, display_phone_number, verified_name, status} dicts.
    """
    async with _build_client() as client:
        response = await client.get(
            f"/{waba_id}/phone_numbers",
            params={"fields": "id,display_phone_number,verified_name,status"},
            headers={"Authorization": f"Bearer {user_token}"},
        )
    data = _raise_for_status(response)
    numbers: list[dict[str, Any]] = data.get("data", [])
    logger.info(
        "phone_numbers_fetched", extra={"waba_id": waba_id, "count": len(numbers)}
    )
    return numbers


# ---------------------------------------------------------------------------
# System User assignment
# ---------------------------------------------------------------------------


async def assign_system_user(waba_id: str, user_token: str) -> bool:
    """
    Grant the platform System User access to a tenant's WABA. Called once
    during onboarding, after code exchange — afterward,
    settings.whatsapp_system_user_token can send on behalf of this WABA
    indefinitely, no per-tenant token needed.

    Meta endpoint:
      POST /{waba_id}/assigned_users
        ?user=SYSTEM_USER_ID
        &tasks=["MANAGE","DEVELOP"]
        Authorization: Bearer USER_TOKEN   ← tenant's short-lived Embedded Signup token

    Returns True on success.
    """
    async with _build_client() as client:
        response = await client.post(
            f"/{waba_id}/assigned_users",
            params={
                "user": settings.whatsapp_system_user_id,
                "tasks": '["MANAGE","DEVELOP"]',
            },
            headers={"Authorization": f"Bearer {user_token}"},
        )
    data = _raise_for_status(response)
    success: bool = data.get("success", False)
    logger.info(
        "system_user_assigned",
        extra={
            "waba_id": waba_id,
            "system_user_id": settings.whatsapp_system_user_id,
            "success": success,
        },
    )
    return success


# ---------------------------------------------------------------------------
# Webhook subscription
# ---------------------------------------------------------------------------


async def subscribe_webhook(waba_id: str, user_token: str) -> bool:
    """
    Subscribe this Meta App to receive webhook events for the given WABA.
    Called once per WABA after Embedded Signup.

    Meta endpoint:
      POST /{waba_id}/subscribed_apps
        Authorization: Bearer USER_TOKEN

    Returns True on success.
    """
    async with _build_client() as client:
        response = await client.post(
            f"/{waba_id}/subscribed_apps",
            headers={"Authorization": f"Bearer {user_token}"},
        )
    data = _raise_for_status(response)
    success: bool = data.get("success", False)
    logger.info("webhook_subscribed", extra={"waba_id": waba_id, "success": success})
    return success


# ---------------------------------------------------------------------------
# Phone number registration
# ---------------------------------------------------------------------------


async def register_phone_number(
    phone_number_id: str,
    user_token: str,
    pin: str,
) -> bool:
    """
    Register a business phone number for Cloud API use — required once per
    number before it can send/receive messages. `pin` becomes the number's
    two-step verification PIN; the caller generates and persists it (see
    app/core/security.generate_numeric_code, app/core/security.encrypt_secret).

    Meta endpoint:
      POST /{phone_number_id}/register
        {messaging_product: "whatsapp", pin: PIN}
        Authorization: Bearer USER_TOKEN   ← the tenant's Embedded Signup token

    Returns True on success.
    """
    payload = {"messaging_product": "whatsapp", "pin": pin}
    async with _build_client() as client:
        response = await client.post(
            f"/{phone_number_id}/register",
            headers={"Authorization": f"Bearer {user_token}"},
            json=payload,
        )
    data = _raise_for_status(response)
    success: bool = data.get("success", False)
    logger.info(
        "phone_number_registered",
        extra={"phone_number_id": phone_number_id, "success": success},
    )
    return success


# ---------------------------------------------------------------------------
# Solution Partner — credit line sharing
# ---------------------------------------------------------------------------


async def share_credit_line(waba_id: str, waba_currency: str) -> dict[str, Any]:
    """
    Share Retail OS's extended credit line with a tenant's WABA, so the
    tenant never adds their own WhatsApp payment method.

    Must run after assign_system_user has granted the System User access to
    the WABA. Authorized with the platform System User token — this acts on
    *our* credit line resource, not the tenant's.

    Meta endpoint:
      POST /{extended_credit_id}/whatsapp_credit_sharing_and_attach
        {waba_currency: ISO-4217-3 code, waba_id: WABA_ID}
        Authorization: Bearer SYSTEM_USER_TOKEN

    Returns the raw Meta response: {allocation_config_id, waba_id}.
    """
    payload = {"waba_currency": waba_currency, "waba_id": waba_id}
    async with _build_client() as client:
        response = await client.post(
            f"/{settings.whatsapp_extended_credit_id}/whatsapp_credit_sharing_and_attach",
            headers={
                "Authorization": f"Bearer {settings.whatsapp_system_user_token.get_secret_value()}"
            },
            json=payload,
        )
    data = _raise_for_status(response)
    logger.info(
        "credit_line_shared",
        extra={
            "waba_id": waba_id,
            "allocation_config_id": data.get("allocation_config_id"),
        },
    )
    return data


# ---------------------------------------------------------------------------
# Sending messages
# ---------------------------------------------------------------------------


async def send_text_message(
    phone_number_id: str,
    to: str,
    body: str,
    *,
    preview_url: bool = False,
) -> dict[str, Any]:
    """
    Send a plain text message to a WhatsApp number.

    Uses the platform System User token (settings.whatsapp_system_user_token)
    which has permanent access to all tenant WABAs.

    Meta endpoint:
      POST /{phone_number_id}/messages
        Authorization: Bearer SYSTEM_USER_TOKEN

    `to` must be a full E.164 number without the '+' prefix (e.g. '923001234567').
    Returns the raw Meta response {messages: [{id}], contacts: [...]}.
    """
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": body, "preview_url": preview_url},
    }
    async with _build_client() as client:
        response = await client.post(
            f"/{phone_number_id}/messages",
            headers={
                "Authorization": f"Bearer {settings.whatsapp_system_user_token.get_secret_value()}"
            },
            json=payload,
        )
    data = _raise_for_status(response)
    msg_id = data.get("messages", [{}])[0].get("id", "unknown")
    logger.info(
        "message_sent",
        extra={"phone_number_id": phone_number_id, "to": to, "message_id": msg_id},
    )
    return data


async def send_interactive_message(
    phone_number_id: str,
    to: str,
    interactive: dict[str, Any],
) -> dict[str, Any]:
    """
    Send an interactive message (buttons, list, etc.).

    `interactive` is the full Meta interactive object:
      {type: "button", body: {text: ...}, action: {buttons: [...]}}

    Returns the raw Meta response.
    """
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": interactive,
    }
    async with _build_client() as client:
        response = await client.post(
            f"/{phone_number_id}/messages",
            headers={
                "Authorization": f"Bearer {settings.whatsapp_system_user_token.get_secret_value()}"
            },
            json=payload,
        )
    return _raise_for_status(response)


async def mark_message_read(
    phone_number_id: str,
    message_id: str,
) -> None:
    """
    Mark an inbound message as read (shows blue ticks to sender).

    Meta endpoint:
      POST /{phone_number_id}/messages
        {status: "read", message_id: MESSAGE_ID}
    """
    payload = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id,
    }
    async with _build_client() as client:
        response = await client.post(
            f"/{phone_number_id}/messages",
            headers={
                "Authorization": f"Bearer {settings.whatsapp_system_user_token.get_secret_value()}"
            },
            json=payload,
        )
    _raise_for_status(response)
    logger.debug("message_marked_read", extra={"message_id": message_id})
