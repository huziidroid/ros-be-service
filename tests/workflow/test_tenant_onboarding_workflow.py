"""
Workflow-level tests for TenantOnboardingWorkflow, using Temporal's test
environment with every activity replaced by a mock (matched by activity
name, per Temporal's standard testing pattern — see
https://docs.temporal.io/develop/python/testing-suite). No real Meta API
calls or database access happen here; this exercises orchestration logic
only (which activities run, in what order, how failures are handled, and
what onboarding_status/credit_shared the workflow settles on).

Requires network access to fetch Temporal's ephemeral test server on first
run (`WorkflowEnvironment.start_time_skipping()`), so these are skipped in
network-restricted sandboxes — run via `make test` in a normal dev environment.
"""

import uuid

import pytest
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from app.schemas.workflows import PhoneNumberInfo, WABAInfo
from app.schemas.workflows.tenant_onboarding import (
    AssignSystemUserInput,
    FetchPhoneNumbersInput,
    OnboardingStatus,
    RegisterPhoneNumberInput,
    RegisterTenantInput,
    SelectPrimaryWabaInput,
    ShareCreditLineInput,
    SubscribeWebhookInput,
    TenantOnboardingInput,
    TenantOnboardingResult,
)
from app.workflows.tenant_onboarding import TenantOnboardingWorkflow


TASK_QUEUE = "test-tenant-onboarding-queue"

_WABA = WABAInfo(id="waba-1", name="Test Distributor", currency="PKR")
_PHONE = PhoneNumberInfo(
    id="phone-1",
    display_phone_number="+923001234567",
    verified_name="Test Distributor",
    status="CONNECTED",
)


def _mock_activities(
    *,
    waba_accounts: list[WABAInfo] = (_WABA,),  # type: ignore[assignment]
    phone_numbers: list[PhoneNumberInfo] = (_PHONE,),  # type: ignore[assignment]
    register_phone_number_fails: bool = False,
    credit_share_succeeds: bool = True,
):
    """Build a fresh set of mock activities for one test scenario."""

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
        return "allocation-config-1" if credit_share_succeeds else None

    @activity.defn(name="fetch_phone_numbers")
    async def fetch_phone_numbers(
        inp: FetchPhoneNumbersInput,
    ) -> list[PhoneNumberInfo]:
        return list(phone_numbers)

    @activity.defn(name="register_phone_number")
    async def register_phone_number(inp: RegisterPhoneNumberInput) -> str:
        if register_phone_number_fails:
            raise ApplicationError("registration failed", type="META_API_ERROR")
        return "encrypted-pin"

    @activity.defn(name="send_test_message")
    async def send_test_message(phone_number_id: str) -> bool:
        return False

    @activity.defn(name="register_tenant")
    async def register_tenant(inp: RegisterTenantInput) -> TenantOnboardingResult:
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
        register_phone_number,
        send_test_message,
        register_tenant,
    ]


async def _run(env: WorkflowEnvironment, activities, inp: TenantOnboardingInput):
    async with Worker(
        env.client,
        task_queue=TASK_QUEUE,
        workflows=[TenantOnboardingWorkflow],
        activities=activities,
    ):
        return await env.client.execute_workflow(
            TenantOnboardingWorkflow.run,
            inp,
            id=f"test-tenant-onboarding-{uuid.uuid4()}",
            task_queue=TASK_QUEUE,
        )


@pytest.fixture
async def env():
    async with await WorkflowEnvironment.start_time_skipping() as env:
        yield env


async def test_happy_path_registers_complete_tenant(env: WorkflowEnvironment) -> None:
    result = await _run(
        env,
        _mock_activities(),
        TenantOnboardingInput(code="good-code", tenant_id="test-tenant-id"),
    )
    assert result.onboarding_status == OnboardingStatus.COMPLETE
    assert result.credit_shared is True
    assert result.waba_id == _WABA.id
    assert [p.id for p in result.phone_numbers] == [_PHONE.id]


async def test_finish_only_waba_registers_waba_only_tenant(
    env: WorkflowEnvironment,
) -> None:
    result = await _run(
        env,
        _mock_activities(phone_numbers=[]),
        TenantOnboardingInput(code="waba-only-code", tenant_id="test-tenant-id"),
    )
    assert result.onboarding_status == OnboardingStatus.WABA_ONLY
    assert result.phone_numbers == []
    # Credit sharing is independent of phone number selection.
    assert result.credit_shared is True


async def test_no_waba_raises_non_retryable_error(env: WorkflowEnvironment) -> None:
    with pytest.raises(WorkflowFailureError) as exc_info:
        await _run(
            env,
            _mock_activities(waba_accounts=[]),
            TenantOnboardingInput(code="no-waba-code", tenant_id="test-tenant-id"),
        )
    cause = exc_info.value.cause
    assert isinstance(cause, ApplicationError)
    assert cause.type == "NO_WABA"


async def test_phone_registration_failure_is_non_fatal(
    env: WorkflowEnvironment,
) -> None:
    result = await _run(
        env,
        _mock_activities(register_phone_number_fails=True),
        TenantOnboardingInput(code="phone-fail-code", tenant_id="test-tenant-id"),
    )
    assert result.onboarding_status == OnboardingStatus.PHONE_UNREGISTERED


async def test_credit_share_failure_is_non_fatal(env: WorkflowEnvironment) -> None:
    result = await _run(
        env,
        _mock_activities(credit_share_succeeds=False),
        TenantOnboardingInput(code="credit-fail-code", tenant_id="test-tenant-id"),
    )
    assert result.onboarding_status == OnboardingStatus.COMPLETE
    assert result.credit_shared is False


async def test_preferred_waba_id_selects_correct_waba(
    env: WorkflowEnvironment,
) -> None:
    other_waba = WABAInfo(id="waba-2", name="Other Distributor", currency="PKR")
    result = await _run(
        env,
        _mock_activities(waba_accounts=[_WABA, other_waba]),
        TenantOnboardingInput(
            code="multi-waba-code",
            tenant_id="test-tenant-id",
            preferred_waba_id="waba-2",
        ),
    )
    assert result.waba_id == "waba-2"
