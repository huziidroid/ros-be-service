"""
Tenant onboarding service.

Owns the TenantOnboardingWorkflow reference (so api/ never imports workflow
classes) and the Temporal-error → AppError translation (so routers stay
thin and raise nothing themselves).

Mapping:
  ApplicationError (NO_WABA)                     → UnprocessableError (422)
  ApplicationError (TENANT_CONFLICT)             → ConflictError (409)
  Any other workflow/activity failure            → UpstreamError (502)
  WorkflowAlreadyStartedError (double callback)  → UnprocessableError (422)

A missing phone number is not a hard failure — FINISH_ONLY_WABA is a
documented successful Embedded Signup completion type, so the workflow
registers a waba_only tenant instead of raising. NO_WABA is the only hard
failure, since nothing can be onboarded without a WABA at all.

Client.execute_workflow() always wraps a workflow-run failure in
WorkflowFailureError — never raises ActivityError/ApplicationError directly
at this level, even when the workflow itself raises ApplicationError or an
activity does. .cause on that exception is the underlying error; if the
failure came from an activity, .cause is an ActivityError whose own .cause
is the ApplicationError raised inside the activity. Both shapes are
unwrapped below before branching on ApplicationError.type.
"""

import logging
from datetime import timedelta

from temporalio.client import Client, WorkflowFailureError
from temporalio.exceptions import (
    ActivityError,
    ApplicationError,
    WorkflowAlreadyStartedError,
)

from app.core.exceptions import ConflictError, UnprocessableError, UpstreamError
from app.core.settings import settings
from app.schemas.workflows.tenant_onboarding import (
    TenantOnboardingInput,
    TenantOnboardingResult,
)
from app.workflows.tenant_onboarding import TenantOnboardingWorkflow


logger = logging.getLogger(__name__)


async def run_tenant_onboarding(
    temporal: Client,
    code: str,
    tenant_id: str,
    preferred_waba_id: str | None = None,
) -> TenantOnboardingResult:
    """
    Execute TenantOnboardingWorkflow synchronously and return the result.

    tenant_id is the authenticated caller's tenant (see
    app/api/v1/auth/whatsapp.py) — WhatsApp connect is an authenticated,
    optional step performed after signup, so the tenant row already exists
    and this attaches the WABA to it rather than creating a new one.

    Raises AppError subclasses only (never raw Temporal exceptions), so the
    api layer needs no try/except.
    """
    try:
        return await temporal.execute_workflow(
            TenantOnboardingWorkflow.run,
            TenantOnboardingInput(
                code=code, tenant_id=tenant_id, preferred_waba_id=preferred_waba_id
            ),
            id=f"tenant-onboarding-{code}",
            task_queue=settings.temporal_task_queue,
            execution_timeout=timedelta(minutes=5),
        )
    except WorkflowAlreadyStartedError as exc:
        # The same signup code is already being processed (duplicate callback).
        logger.warning("tenant_onboarding_duplicate", extra={"error": str(exc)})
        raise UnprocessableError(
            "This signup is already being processed.",
            internal_detail=str(exc),
        ) from exc
    except WorkflowFailureError as exc:
        cause: BaseException | None = exc.cause
        # Activity-raised errors arrive one level deeper, wrapped in
        # ActivityError — unwrap to get at the ApplicationError itself.
        if isinstance(cause, ActivityError):
            cause = cause.cause
        if isinstance(cause, ApplicationError):
            if cause.type == "TENANT_CONFLICT":
                logger.warning(
                    "tenant_onboarding_conflict", extra={"error": str(cause)}
                )
                raise ConflictError(str(cause), internal_detail=str(exc)) from exc
            # Domain-level failure — e.g. NO_WABA, raised by the workflow
            # itself or surfaced through an activity.
            logger.warning("tenant_onboarding_failed", extra={"error": str(cause)})
            raise UnprocessableError(str(cause), internal_detail=str(exc)) from exc
        logger.error("tenant_onboarding_workflow_failed", extra={"error": str(exc)})
        raise UpstreamError(internal_detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — translate everything to a typed error
        logger.error("tenant_onboarding_error", extra={"error": str(exc)})
        raise UpstreamError(internal_detail=str(exc)) from exc
