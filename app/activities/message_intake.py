"""
Message intake activities.

log_message emits a structured log event for each inbound message — the
only activity MessageIntakeWorkflow calls today (Phase 1). Later phases add
classify_message, extract_order, resolve_products, and send_confirmation.
"""

import logging

from temporalio import activity

from app.schemas.workflows.message_intake import MessageIntakeInput


logger = logging.getLogger(__name__)


@activity.defn
async def log_message(inp: MessageIntakeInput) -> None:
    """Emit a structured log event for the inbound message."""
    # Do NOT log message content (text_body) or the raw sender number at INFO —
    # that is customer PII / business data. Log identifiers and metadata only.
    message = inp.message
    text_body = message.text_body
    logger.info(
        "message_intake_activity",
        extra={
            "wamid": message.id,
            "message_type": message.type,
            "phone_number_id": inp.phone_number_id,
            "has_text": text_body is not None,
            "text_len": len(text_body) if text_body else 0,
            "has_media": message.media_id is not None,
            "timestamp": message.timestamp,
            "tenant_waba_id": inp.tenant_waba_id,
        },
    )
