"""
Message intake service — resolves each inbound webhook message to its tenant and
delivers it to that conversation's ConversationWorkflow (one long-running workflow
per tenant_waba_id + wa_id, not per message).

Delivery uses signal-with-start: the first message for a conversation starts the
workflow with `start_signal`; every later message signals the existing execution.
`id_conflict_policy=USE_EXISTING` makes the start a no-op when the workflow already
exists.
"""

import asyncio
import logging
from collections import defaultdict

from sqlalchemy.ext.asyncio import AsyncSession
from temporalio.client import Client, WorkflowHandle
from temporalio.common import WorkflowIDConflictPolicy

from app.core.settings import settings
from app.repositories.tenant_repo import TenantRepo
from app.schemas.webhooks.whatsapp import (
    InboundMessage,
    WhatsAppWebhookPayload,
)
from app.schemas.workflows.conversation import (
    ConversationWorkflowConfig,
    NewMessageSignal,
)
from app.workflows.conversation import ConversationWorkflow


logger = logging.getLogger(__name__)


async def ingest_webhook(
    session: AsyncSession,
    temporal: Client,
    event: WhatsAppWebhookPayload,
) -> int:
    """
    Resolve each inbound message to its tenant and deliver it to that
    conversation's ConversationWorkflow. Returns the count delivered.

    Tenant lookups are deduplicated per phone_number_id. Messages for
    unknown phone_number_ids are logged and dropped. Different conversations
    are signaled concurrently; messages within the same conversation are
    signaled in order.
    """
    messages = _extract_messages(event)
    if not messages:
        return 0

    signals = await _resolve_signals(session, messages)
    if not signals:
        return 0

    grouped = _group_by_conversation(signals)
    results = await asyncio.gather(
        *[
            _deliver_to_conversation(temporal, conversation_id, group)
            for conversation_id, group in grouped.items()
        ]
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


async def _resolve_signals(
    session: AsyncSession,
    messages: list[tuple[str, InboundMessage]],
) -> list[NewMessageSignal]:
    """
    Resolve each (phone_number_id, message) pair to its tenant, deduplicating
    lookups per phone_number_id. Messages for unknown phone_number_ids are
    logged and dropped.
    """
    repo = TenantRepo(session)
    waba_id_cache: dict[str, str | None] = {}  # phone_number_id -> waba_id | None
    signals: list[NewMessageSignal] = []

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

        signals.append(
            NewMessageSignal(
                phone_number_id=phone_number_id,
                tenant_waba_id=tenant_waba_id,
                message=message,
            )
        )

    return signals


def _conversation_id(signal: NewMessageSignal) -> str:
    return f"conv-{signal.tenant_waba_id}-{signal.message.from_}"


def _group_by_conversation(
    signals: list[NewMessageSignal],
) -> dict[str, list[NewMessageSignal]]:
    """Groups preserve arrival order within each conversation — required, since a
    conversation's own messages must be delivered in order."""
    grouped: dict[str, list[NewMessageSignal]] = defaultdict(list)
    for signal in signals:
        grouped[_conversation_id(signal)].append(signal)
    return grouped


async def _deliver_to_conversation(
    temporal: Client,
    conversation_id: str,
    signals: list[NewMessageSignal],
) -> int:
    """
    Deliver every signal in this conversation's group, in order. The first signal
    starts the workflow if it doesn't exist yet (USE_EXISTING makes this a no-op
    start, not an error, if it does); every signal after that goes to the handle
    from the first call.
    """
    handle: WorkflowHandle[ConversationWorkflow, None] | None = None
    delivered = 0

    for signal in signals:
        if handle is None:
            handle = await temporal.start_workflow(
                ConversationWorkflow.run,
                args=[ConversationWorkflowConfig.from_settings()],
                id=conversation_id,
                task_queue=settings.temporal_task_queue,
                start_signal="new_message",
                start_signal_args=[signal],
                id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
            )
        else:
            await handle.signal(ConversationWorkflow.new_message, signal)

        delivered += 1
        logger.info(
            "conversation_signaled",
            extra={
                "conversation_id": conversation_id,
                "wamid": signal.message.id,
                "message_type": signal.message.type,
            },
        )

    return delivered
