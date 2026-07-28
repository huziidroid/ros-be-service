"""
Service-level tests for run_tenant_onboarding's Temporal error translation.

Client.execute_workflow() always wraps a workflow-run failure in
WorkflowFailureError — it never raises ApplicationError/ActivityError
directly at the call site (see app/services/onboarding.py's module
docstring for the exact unwrapping). These tests exercise
run_tenant_onboarding() itself, not just the workflow, against Temporal's
test environment — a regression back to catching ActivityError/
ApplicationError directly at that level would make both tests below fail,
since every failure would then fall through to the generic UpstreamError
branch instead of the specific ConflictError/UnprocessableError one.

Same test infrastructure and mock-activity pattern as
test_tenant_onboarding_workflow.py; see that file for the network-access
caveat (skipped in network-restricted sandboxes, run via `make test`).
"""

import pytest
from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from app.core.exceptions import ConflictError, UnprocessableError
from app.core.settings import settings
from app.schemas.workflows import PhoneNumberInfo, WABAInfo
from app.schemas.workflows.tenant_onboarding import (
    AssignSystemUserInput,
    FetchPhoneNumbersInput,
    RegisterTenantInput,
    SelectPrimaryWabaInput,
    ShareCreditLineInput,
    SubscribeWebhookInput,
    TenantOnboardingResult,
)
from app.services.onboarding import run_tenant_onboarding
from app.workflows.tenant_onboarding import TenantOnboardingWorkflow


TASK_QUEUE = "test-onboarding-service-queue"

_WABA = WABAInfo(id="waba-1", name="Test Distributor", currency="PKR")


def _mock_activities(
    *,
    waba_accounts: list[WABAInfo] | None = None,
    register_tenant_conflict: bool = False,
):
    """
    Happy-path activities up through register_tenant, which either succeeds
    or raises the same TENANT_CONFLICT ApplicationError
    app/activities/tenant_onboarding.py::register_tenant raises when
    TenantRepo.attach_waba finds a cross-tenant collision.

    fetch_phone_numbers returns [] so the workflow skips
    register_phone_number/send_test_message entirely — irrelevant to what's
    under test here (error translation, not phone registration).
    """
    if waba_accounts is None:
        waba_accounts = [_WABA]

    @activity.defn(name="exchange_code")
    async def exchange_code(code: str) -> str:
        return "fake-user-token"

    @activity.defn(name="fetch_waba_accounts")
    async def fetch_waba_accounts(user_token: str) -> list[WABAInfo]:
        return list(waba_accounts)

    @activity.defn(name="select_primary_waba")
    async def select_primary_waba(inp: SelectPrimaryWabaInput) -> WABAInfo:
        from app.domain.onboarding import select_primary_waba as _select

        return _select(inp.waba_accounts, inp.preferred_waba_id)

    @activity.defn(name="assign_system_user")
    async def assign_system_user(inp: AssignSystemUserInput) -> bool:
        return True

    @activity.defn(name="subscribe_waba_webhook")
    async def subscribe_waba_webhook(inp: SubscribeWebhookInput) -> bool:
        return True

    @activity.defn(name="share_credit_line")
    async def share_credit_line(inp: ShareCreditLineInput) -> str | None:
        return "allocation-config-1"

    @activity.defn(name="fetch_phone_numbers")
    async def fetch_phone_numbers(
        inp: FetchPhoneNumbersInput,
    ) -> list[PhoneNumberInfo]:
        return []

    @activity.defn(name="register_tenant")
    async def register_tenant(inp: RegisterTenantInput) -> TenantOnboardingResult:
        if register_tenant_conflict:
            raise ApplicationError(
                "This WhatsApp Business Account is already connected to "
                "another Retail OS account.",
                type="TENANT_CONFLICT",
                non_retryable=True,
            )
        return TenantOnboardingResult(
            waba_id=inp.waba_id,
            display_name=inp.display_name,
            onboarding_status=inp.onboarding_status,
            phone_numbers=inp.all_phone_numbers,
            credit_shared=inp.allocation_config_id is not None,
        )

    return [
        exchange_code,
        fetch_waba_accounts,
        select_primary_waba,
        assign_system_user,
        subscribe_waba_webhook,
        share_credit_line,
        fetch_phone_numbers,
        register_tenant,
    ]


@pytest.fixture
async def env():
    async with await WorkflowEnvironment.start_time_skipping() as env:
        yield env


async def _run_service(
    env: WorkflowEnvironment,
    activities,
    monkeypatch: pytest.MonkeyPatch,
    *,
    code: str,
    tenant_id: str,
):
    # run_tenant_onboarding hardcodes settings.temporal_task_queue; point it
    # at this test's queue so the mock Worker actually picks the run up.
    monkeypatch.setattr(settings, "temporal_task_queue", TASK_QUEUE)
    async with Worker(
        env.client,
        task_queue=TASK_QUEUE,
        workflows=[TenantOnboardingWorkflow],
        activities=activities,
    ):
        return await run_tenant_onboarding(env.client, code=code, tenant_id=tenant_id)


async def test_no_waba_maps_to_unprocessable_error(
    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Workflow-raised ApplicationError(type=NO_WABA) → UnprocessableError (422)."""
    with pytest.raises(UnprocessableError):
        await _run_service(
            env,
            _mock_activities(waba_accounts=[]),
            monkeypatch,
            code="no-waba-code",
            tenant_id="test-tenant-id",
        )


async def test_tenant_conflict_maps_to_conflict_error(
    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Activity-raised ApplicationError(type=TENANT_CONFLICT) → ConflictError (409).

    This is the case that specifically requires unwrapping ActivityError.cause
    (one level deeper than the NO_WABA case above, which the workflow raises
    directly) — the regression this test guards against.
    """
    with pytest.raises(ConflictError):
        await _run_service(
            env,
            _mock_activities(register_tenant_conflict=True),
            monkeypatch,
            code="conflict-code",
            tenant_id="test-tenant-id",
        )
