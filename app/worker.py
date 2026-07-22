"""
Temporal worker entry point.

Run with: make worker (or: uv run python -m app.worker)

Polls the task queue and executes registered activities + workflows. Must be
running for any workflow-backed endpoint to function. Also ensures the
recurring TenantReconciliationWorkflow schedule exists (idempotent — safe
with multiple worker replicas; see app/clients/temporal.py::ensure_reconciliation_schedule).

Every activity a workflow calls via workflow.execute_activity must be listed
in the `activities=[...]` below, or Temporal schedules it and hangs waiting
for a worker that can never claim it — no loud failure, just a stuck task.
"""

import asyncio
import logging

from temporalio.client import Client
from temporalio.worker import Worker

from app.activities.message_intake import log_message
from app.activities.tenant_onboarding import (
    assign_system_user,
    exchange_code,
    fetch_phone_numbers,
    fetch_waba_accounts,
    register_phone_number,
    register_tenant,
    select_primary_waba,
    send_test_message,
    share_credit_line,
    subscribe_waba_webhook,
)
from app.activities.tenant_reconciliation import (
    fetch_waba_currency,
    list_tenants_needing_credit_share,
    list_tenants_needing_phone_registration,
    mark_credit_shared,
    mark_phone_registered,
)
from app.clients.temporal import ensure_reconciliation_schedule
from app.core.logger import configure_logging
from app.core.settings import settings
from app.workflows.message_intake import MessageIntakeWorkflow
from app.workflows.tenant_onboarding import TenantOnboardingWorkflow
from app.workflows.tenant_reconciliation import TenantReconciliationWorkflow


configure_logging(settings)
logger = logging.getLogger(__name__)


async def main() -> None:
    logger.info(
        "worker_starting",
        extra={
            "host": settings.temporal_host,
            "namespace": settings.temporal_namespace,
            "task_queue": settings.temporal_task_queue,
        },
    )

    client = await Client.connect(
        settings.temporal_host,
        namespace=settings.temporal_namespace,
    )

    await ensure_reconciliation_schedule(client)

    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=[
            TenantOnboardingWorkflow,
            TenantReconciliationWorkflow,
            MessageIntakeWorkflow,
        ],
        activities=[
            # Tenant onboarding
            exchange_code,
            fetch_waba_accounts,
            select_primary_waba,
            assign_system_user,
            subscribe_waba_webhook,
            share_credit_line,
            fetch_phone_numbers,
            register_phone_number,
            send_test_message,
            register_tenant,
            # Tenant reconciliation
            list_tenants_needing_credit_share,
            list_tenants_needing_phone_registration,
            fetch_waba_currency,
            mark_credit_shared,
            mark_phone_registered,
            # Message intake
            log_message,
        ],
    )

    logger.info("worker_running", extra={"task_queue": settings.temporal_task_queue})
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
