"""
Meta WhatsApp Cloud API client — outbound Graph API calls.

Message sends use settings.whatsapp_system_user_token (non-expiring, valid
across all tenant WABAs). Non-2xx responses raise WhatsAppAPIError.
"""

import logging
from typing import Any

import httpx

from app.core.settings import settings


logger = logging.getLogger(__name__)


class WhatsAppAPIError(Exception):
    """Raised when the Meta Graph API returns a non-2xx response."""

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
        # Log only the path — query strings can carry access_token/client_secret.
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


# --- Embedded Signup: code exchange ---


async def exchange_code_for_token(code: str) -> str:
    """Exchange a short-lived Embedded Signup code for a user access token."""
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


# --- WABA and phone number discovery ---


async def get_waba_accounts(user_token: str) -> list[dict[str, Any]]:
    """List WhatsApp Business Accounts accessible with the given user token."""
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
    """Fetch a WABA's info via the platform System User token (used by reconciliation)."""
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
    """List phone numbers registered under a WABA."""
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


# --- System User assignment ---


async def assign_system_user(waba_id: str, user_token: str) -> bool:
    """Grant the platform System User permanent access to a tenant's WABA (once, at onboarding)."""
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


# --- Webhook subscription ---


async def subscribe_webhook(waba_id: str, user_token: str) -> bool:
    """Subscribe this Meta App to webhook events for the given WABA."""
    async with _build_client() as client:
        response = await client.post(
            f"/{waba_id}/subscribed_apps",
            headers={"Authorization": f"Bearer {user_token}"},
        )
    data = _raise_for_status(response)
    success: bool = data.get("success", False)
    logger.info("webhook_subscribed", extra={"waba_id": waba_id, "success": success})
    return success


# --- Phone number registration ---


async def register_phone_number(
    phone_number_id: str,
    user_token: str,
    pin: str,
) -> bool:
    """Register a phone number for Cloud API use; `pin` becomes its two-step verification PIN."""
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


# --- Solution Partner: credit line sharing ---


async def share_credit_line(waba_id: str, waba_currency: str) -> dict[str, Any]:
    """Share the platform's extended credit line with a tenant's WABA (System User token)."""
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


# --- Sending messages ---


async def send_text_message(
    phone_number_id: str,
    to: str,
    body: str,
    *,
    preview_url: bool = False,
) -> dict[str, Any]:
    """Send a plain text message. `to` is E.164 without the '+' prefix."""
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


async def send_authentication_template(
    phone_number_id: str,
    to: str,
    *,
    template_name: str,
    language: str,
    code: str,
) -> dict[str, Any]:
    """
    Send an OTP via an approved copy-code AUTHENTICATION template (delivers
    without a 24h session). Meta requires the code twice: as the body variable
    and as the copy-code button's `coupon_code`.
    """
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language},
            "components": [
                {"type": "body", "parameters": [{"type": "text", "text": code}]},
                {
                    "type": "button",
                    "sub_type": "copy_code",
                    "index": "0",
                    "parameters": [{"type": "coupon_code", "coupon_code": code}],
                },
            ],
        },
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
        "template_message_sent",
        extra={
            "phone_number_id": phone_number_id,
            "to": to,
            "template": template_name,
            "message_id": msg_id,
        },
    )
    return data


async def send_interactive_message(
    phone_number_id: str,
    to: str,
    interactive: dict[str, Any],
) -> dict[str, Any]:
    """Send an interactive message; `interactive` is the full Meta interactive object."""
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
    """Mark an inbound message as read (blue ticks to the sender)."""
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
