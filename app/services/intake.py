"""
Message intake service.

Owns the webhook → workflow fan-out, so the router stays thin and never
imports workflow classes, repositories, or models directly — it only
verifies the signature, parses the body, and delegates to ingest_webhook().
"""

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession
from temporalio.client import Client
from temporalio.exceptions import WorkflowAlreadyStartedError

from app.core.settings import settings
from app.repositories.tenant_repo import TenantRepo
from app.schemas.webhooks.whatsapp import (
    InboundMessage,
    WhatsAppWebhookPayload,
)
from app.schemas.workflows.message_intake import MessageIntakeInput
from app.workflows.message_intake import MessageIntakeWorkflow


logger = logging.getLogger(__name__)


async def ingest_webhook(
    session: AsyncSession,
    temporal: Client,
    event: WhatsAppWebhookPayload,
) -> int:
    """
    Resolve each inbound message to its tenant and start one
    MessageIntakeWorkflow per message. Returns the count started.

    Tenant lookups are deduplicated per phone_number_id. Messages for
    unknown phone_number_ids are logged and dropped. Known-tenant workflow
    starts are issued concurrently.
    """
    messages = _extract_messages(event)
    if not messages:
        return 0

    workflow_inputs = await _resolve_workflow_inputs(session, messages)

    results = await asyncio.gather(
        *[_start_message_intake(temporal, inp) for inp in workflow_inputs]
    )
    return sum(results)


def _extract_messages(
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


async def _resolve_workflow_inputs(
    session: AsyncSession,
    messages: list[tuple[str, InboundMessage]],
) -> list[MessageIntakeInput]:
    """
    Resolve each (phone_number_id, message) pair to its tenant, deduplicating
    lookups per phone_number_id. Messages for unknown phone_number_ids are
    logged and dropped.
    """
    repo = TenantRepo(session)
    waba_id_cache: dict[str, str | None] = {}  # phone_number_id -> waba_id | None
    workflow_inputs: list[MessageIntakeInput] = []

    for phone_number_id, message in messages:
        if phone_number_id not in waba_id_cache:
            tenant = await repo.get_by_phone_number_id(phone_number_id)
            waba_id_cache[phone_number_id] = tenant.waba_id if tenant else None

        tenant_waba_id = waba_id_cache[phone_number_id]
        if tenant_waba_id is None:
            logger.warning(
                "webhook_unknown_tenant",
                extra={"phone_number_id": phone_number_id, "wamid": message.id},
            )
            continue

        workflow_inputs.append(
            MessageIntakeInput(
                phone_number_id=phone_number_id,
                tenant_waba_id=tenant_waba_id,
                message=message,
            )
        )

    return workflow_inputs


async def _start_message_intake(
    temporal: Client,
    inp: MessageIntakeInput,
) -> bool:
    """
    Fire-and-forget: start a MessageIntakeWorkflow for one inbound message.
    Returns False if one is already running (Temporal dedup).
    """
    try:
        await temporal.start_workflow(
            MessageIntakeWorkflow.run,
            inp,
            id=f"message-{inp.message.id}",
            task_queue=settings.temporal_task_queue,
        )
        logger.info(
            "message_workflow_started",
            extra={
                "wamid": inp.message.id,
                "phone_number_id": inp.phone_number_id,
                "message_type": inp.message.type,
            },
        )
        return True
    except WorkflowAlreadyStartedError:
        # Meta retried a message we're already processing — safe to ignore.
        logger.info("message_workflow_deduplicated", extra={"wamid": inp.message.id})
        return False
