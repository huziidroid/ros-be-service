"""
MessageIntakeWorkflow

Triggered by: POST /api/v1/webhooks/whatsapp (fire-and-forget).
Workflow ID: message-{wamid} — Temporal rejects a duplicate start, so a
message Meta redelivers is naturally deduped.

Phase 1: log_message — structured event log confirming the message reached
the workflow layer.

Phase 2+ (future): classify_message → resolve_contact → extract_order →
resolve_products → send_confirmation → persist_order.
"""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy


with workflow.unsafe.imports_passed_through():
    from app.activities.message_intake import log_message
    from app.schemas.workflows.message_intake import MessageIntakeInput


_TIMEOUT = timedelta(seconds=30)
_RETRY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
)


@workflow.defn
class MessageIntakeWorkflow:
    @workflow.run
    async def run(self, inp: MessageIntakeInput) -> None:
        # Phase 1 — structured event log
        await workflow.execute_activity(
            log_message,
            inp,
            start_to_close_timeout=_TIMEOUT,
            retry_policy=_RETRY,
        )

        # Phase 2+ activities will be chained here:
        # classified = await workflow.execute_activity(classify_message, inp, ...)
        # if classified.intent == "new_order":
        #     await workflow.execute_activity(extract_order, ..., ...)
        #     ...
