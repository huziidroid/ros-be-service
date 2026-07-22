"""
WhatsApp webhook handler (thin router).

GET  /webhooks/whatsapp — Meta's one-time verification handshake.
POST /webhooks/whatsapp — inbound events (messages + delivery statuses).

  - GET compares hub.verify_token against settings.whatsapp_webhook_secret.
  - POST verifies X-Hub-Signature-256 using settings.whatsapp_app_secret, not
    the verify token.
  - Malformed/unmodeled payloads are acked with 200, never 500, so Meta
    doesn't retry forever.
  - Tenant lookup + workflow fan-out live in services/intake.ingest_webhook;
    the router only verifies, parses, and delegates.

GET returns a raw PlainTextResponse (Meta requires the bare hub.challenge) —
the one exception to the APIResponse envelope used everywhere else.
"""

import logging

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import ValidationError

from app.api.dependencies import SessionDep, TemporalDep
from app.core.settings import settings
from app.domain.webhook import verify_signature
from app.schemas.response import APIResponse, ok
from app.schemas.webhooks.whatsapp import WebhookAckData, WhatsAppWebhookPayload
from app.services.intake import ingest_webhook


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/whatsapp", tags=["WhatsApp Webhooks"])


# ---------------------------------------------------------------------------
# GET — Meta webhook verification
# ---------------------------------------------------------------------------


@router.get("")
async def verify_webhook(
    hub_mode: str = Query(alias="hub.mode"),
    hub_challenge: str = Query(alias="hub.challenge"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
) -> PlainTextResponse:
    """
    Meta calls this once when you register the webhook URL.
    Echo back hub.challenge as plain text to confirm ownership.
    """
    expected_token = settings.whatsapp_webhook_secret.get_secret_value()
    if hub_mode != "subscribe" or hub_verify_token != expected_token:
        logger.warning("webhook_verification_failed", extra={"mode": hub_mode})
        raise HTTPException(status_code=403, detail="Verification failed")

    logger.info("webhook_verified")
    return PlainTextResponse(content=hub_challenge)


# ---------------------------------------------------------------------------
# POST — Inbound events
# ---------------------------------------------------------------------------


@router.post("", response_model=APIResponse[WebhookAckData])
async def whatsapp_webhook(
    request: Request,
    temporal: TemporalDep,
    session: SessionDep,
) -> APIResponse[WebhookAckData]:
    """
    Receive all WhatsApp events: inbound messages + delivery statuses.

    Verifies the HMAC signature (403 on mismatch), acks 200 once signed
    correctly, and delegates tenant resolution + workflow fan-out to the
    intake service.
    """
    body = await request.body()

    # --- Signature verification (App Secret, per Meta) ---
    signature = request.headers.get("x-hub-signature-256", "")
    if not signature:
        logger.warning("webhook_rejected_missing_signature")
        raise HTTPException(status_code=403, detail="Missing signature")
    if not verify_signature(
        body, signature, settings.whatsapp_app_secret.get_secret_value()
    ):
        logger.warning("webhook_rejected_invalid_signature")
        raise HTTPException(status_code=403, detail="Invalid signature")

    # --- Parse (guarded — never 500 on a signed-but-unmodeled payload) ---
    try:
        event = WhatsAppWebhookPayload.model_validate_json(body)
    except ValidationError as exc:
        # Acknowledge so Meta stops retrying; log for investigation.
        logger.warning(
            "webhook_unparseable_payload", extra={"errors": exc.error_count()}
        )
        return ok(data=WebhookAckData(workflows_started=0), message="Acknowledged.")

    started = await ingest_webhook(session, temporal, event)

    if started == 0:
        return ok(
            data=WebhookAckData(workflows_started=0), message="No messages to process."
        )
    return ok(
        data=WebhookAckData(workflows_started=started), message="Messages queued."
    )
