"""
TenantReconciliationWorkflow

Triggered by a Temporal Schedule (app.clients.temporal.ensure_reconciliation_schedule)
rather than per-request. Overlap policy SKIP prevents overlapping runs.

Retries the two TenantOnboardingWorkflow steps allowed to fail non-fatally:
  1. Credit sharing — for tenants with no allocation_config_id, re-fetch the
     WABA's currency and retry share_credit_line.
  2. Phone registration — for tenants stuck in phone_unregistered, retry
     register_phone_number using the platform System User token (the
     original Embedded Signup token is long gone by now).

Both passes process tenants sequentially; one tenant's failure never blocks
the rest — it's just retried next run.
"""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy


with workflow.unsafe.imports_passed_through():
    from app.activities.tenant_onboarding import (
        register_phone_number,
        share_credit_line,
    )
    from app.activities.tenant_reconciliation import (
        fetch_waba_currency,
        list_tenants_needing_credit_share,
        list_tenants_needing_phone_registration,
        mark_credit_shared,
        mark_phone_registered,
    )
    from app.schemas.workflows.tenant_onboarding import (
        RegisterPhoneNumberInput,
        ShareCreditLineInput,
    )
    from app.schemas.workflows.tenant_reconciliation import (
        MarkCreditSharedInput,
        MarkPhoneRegisteredInput,
        TenantReconciliationResult,
    )


_TIMEOUT = timedelta(minutes=2)
_RETRY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=30),
)


@workflow.defn
class TenantReconciliationWorkflow:
    @workflow.run
    async def run(self) -> TenantReconciliationResult:
        result = TenantReconciliationResult()

        # --- Pass 1: credit sharing ---
        needing_credit_share = await workflow.execute_activity(
            list_tenants_needing_credit_share,
            start_to_close_timeout=_TIMEOUT,
            retry_policy=_RETRY,
        )
        for tenant in needing_credit_share:
            result.credit_shares_attempted += 1
            try:
                currency = await workflow.execute_activity(
                    fetch_waba_currency,
                    tenant.waba_id,
                    start_to_close_timeout=_TIMEOUT,
                    retry_policy=_RETRY,
                )
                allocation_config_id = await workflow.execute_activity(
                    share_credit_line,
                    ShareCreditLineInput(
                        waba_id=tenant.waba_id, waba_currency=currency
                    ),
                    start_to_close_timeout=_TIMEOUT,
                    retry_policy=_RETRY,
                )
                if allocation_config_id is not None:
                    await workflow.execute_activity(
                        mark_credit_shared,
                        MarkCreditSharedInput(
                            waba_id=tenant.waba_id,
                            allocation_config_id=allocation_config_id,
                        ),
                        start_to_close_timeout=_TIMEOUT,
                        retry_policy=_RETRY,
                    )
                    result.credit_shares_succeeded += 1
            except Exception:  # noqa: BLE001 — one tenant's failure must not block the rest
                workflow.logger.warning(
                    "credit_share_reconciliation_failed",
                    extra={"waba_id": tenant.waba_id},
                )

        # --- Pass 2: phone number registration ---
        needing_registration = await workflow.execute_activity(
            list_tenants_needing_phone_registration,
            start_to_close_timeout=_TIMEOUT,
            retry_policy=_RETRY,
        )
        for tenant in needing_registration:
            result.phone_registrations_attempted += 1
            if tenant.phone_number_id is None:
                continue
            try:
                encrypted_pin = await workflow.execute_activity(
                    register_phone_number,
                    RegisterPhoneNumberInput(phone_number_id=tenant.phone_number_id),
                    start_to_close_timeout=_TIMEOUT,
                    retry_policy=_RETRY,
                )
                await workflow.execute_activity(
                    mark_phone_registered,
                    MarkPhoneRegisteredInput(
                        waba_id=tenant.waba_id,
                        two_step_pin_encrypted=encrypted_pin,
                    ),
                    start_to_close_timeout=_TIMEOUT,
                    retry_policy=_RETRY,
                )
                result.phone_registrations_succeeded += 1
            except Exception:  # noqa: BLE001
                workflow.logger.warning(
                    "phone_registration_reconciliation_failed",
                    extra={"waba_id": tenant.waba_id},
                )

        workflow.logger.info(
            "reconciliation_pass_complete",
            extra={
                "credit_shares_attempted": result.credit_shares_attempted,
                "credit_shares_succeeded": result.credit_shares_succeeded,
                "phone_registrations_attempted": result.phone_registrations_attempted,
                "phone_registrations_succeeded": result.phone_registrations_succeeded,
            },
        )
        return result
