"""
Temporal client lifecycle — connecting to and scheduling work on the
Temporal server, same role as clients/whatsapp.py and clients/redis.py play
for their own external services.

connect_temporal() runs once in the FastAPI lifespan, storing the client on
app.state.temporal. The FastAPI dependency lives in app/api/dependencies.py
to keep framework code out of clients/.

ensure_reconciliation_schedule() runs once from app/worker.py at startup —
the worker owns the recurring TenantReconciliationWorkflow schedule since
it's the process with workflows/activities registered.
"""

import logging
from datetime import timedelta

from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
)

from app.core.settings import settings


logger = logging.getLogger(__name__)

RECONCILIATION_SCHEDULE_ID = "tenant-reconciliation-schedule"


async def connect_temporal() -> Client | None:
    """
    Connect to the Temporal server.

    In dev/staging, returns None (with a warning) if unreachable, so the API
    can start without Temporal running — endpoints needing it return 503 via
    app/api/dependencies.py. In production, a failed connection re-raises.
    """
    try:
        logger.info("temporal_connecting", extra={"host": settings.temporal_host})
        client = await Client.connect(
            settings.temporal_host,
            namespace=settings.temporal_namespace,
        )
        logger.info("temporal_connected")
        return client
    except Exception as exc:
        if settings.is_production:
            logger.error(
                "temporal_unavailable_fatal",
                extra={"host": settings.temporal_host, "error": str(exc)},
            )
            raise
        logger.warning(
            "temporal_unavailable",
            extra={"host": settings.temporal_host, "error": str(exc)},
        )
        return None


async def check_health(
    client: Client, *, rpc_timeout: timedelta = timedelta(seconds=3)
) -> bool:
    """True if the Temporal server responds within `rpc_timeout`. False otherwise."""
    try:
        return await client.service_client.check_health(timeout=rpc_timeout)
    except Exception as exc:  # noqa: BLE001 — health checks report status, never raise
        logger.warning("temporal_health_check_failed", extra={"error": str(exc)})
        return False


async def ensure_reconciliation_schedule(client: Client) -> None:
    """
    Idempotently create the recurring schedule for TenantReconciliationWorkflow.

    Safe on every worker startup, including multiple replicas — an
    already-exists error from Temporal is treated as expected, not a
    failure. Any other error is logged and swallowed; this must never block
    the worker from starting.
    """
    # Local import to avoid a module-load-time dependency on workflows/ —
    # this file gets imported early (FastAPI lifespan, worker startup).
    from app.workflows.tenant_reconciliation import TenantReconciliationWorkflow

    try:
        await client.create_schedule(
            RECONCILIATION_SCHEDULE_ID,
            Schedule(
                action=ScheduleActionStartWorkflow(
                    TenantReconciliationWorkflow.run,
                    id="tenant-reconciliation",
                    task_queue=settings.temporal_task_queue,
                ),
                spec=ScheduleSpec(
                    intervals=[
                        ScheduleIntervalSpec(
                            every=timedelta(
                                minutes=settings.reconciliation_interval_minutes
                            )
                        )
                    ]
                ),
                policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
            ),
        )
        logger.info(
            "reconciliation_schedule_created",
            extra={"schedule_id": RECONCILIATION_SCHEDULE_ID},
        )
    except Exception as exc:  # noqa: BLE001 — best-effort; already-exists is expected
        logger.info(
            "reconciliation_schedule_create_skipped",
            extra={"schedule_id": RECONCILIATION_SCHEDULE_ID, "detail": str(exc)},
        )
