"""
Webhook domain helpers — pure functions, no I/O, fully unit-testable.

Kept separate from the router so they're testable without FastAPI.
"""

import hashlib
import hmac

from app.schemas.webhooks.whatsapp import InboundMessage, WhatsAppWebhookPayload


def verify_signature(body: bytes, signature_header: str, secret: str) -> bool:
    """
    Verify the X-Hub-Signature-256 header Meta attaches to every webhook POST.
    Caller is responsible for rejecting requests that return False.
    """
    expected = hmac.new(
        secret.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature_header)


def extract_messages(
    event: WhatsAppWebhookPayload,
) -> list[tuple[str, InboundMessage]]:
    """
    Flatten inbound messages out of the nested Meta envelope into
    (phone_number_id, message) tuples. Status changes and unknown fields
    are silently skipped.
    """
    result: list[tuple[str, InboundMessage]] = []
    for entry in event.entry:
        for change in entry.changes:
            if change.field != "messages":
                continue
            if not change.value.messages:
                continue
            phone_number_id = change.value.metadata.phone_number_id
            for msg in change.value.messages:
                result.append((phone_number_id, msg))
    return result
