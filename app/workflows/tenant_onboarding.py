"""
TenantOnboardingWorkflow — attaches a WABA to an already-signed-up tenant.

Triggered synchronously by POST /api/v1/auth/whatsapp/callback. Workflow ID
tenant-onboarding-{code} prevents double-processing a single-use signup code.
"""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError


with workflow.unsafe.imports_passed_through():
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


_TIMEOUT = timedelta(minutes=2)
_RETRY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=30),
)
_SUBSCRIBE_RETRY = RetryPolicy(
    maximum_attempts=2,
    initial_interval=timedelta(seconds=1),
)
# Meta signup codes are single-use — fail fast, never retry a spent code.
_NO_RETRY = RetryPolicy(maximum_attempts=1)


@workflow.defn
class TenantOnboardingWorkflow:
    @workflow.run
    async def run(self, inp: TenantOnboardingInput) -> TenantOnboardingResult:
        # 1. Exchange code → user access token
        # _NO_RETRY: Meta codes are single-use; retrying a spent code always fails.
        user_token: str = await workflow.execute_activity(
            exchange_code,
            inp.code,
            start_to_close_timeout=_TIMEOUT,
            retry_policy=_NO_RETRY,
        )

        # 2. Fetch all WABAs accessible with this token
        waba_accounts = await workflow.execute_activity(
            fetch_waba_accounts,
            user_token,
            start_to_close_timeout=_TIMEOUT,
            retry_policy=_RETRY,
        )

        if not waba_accounts:
            raise ApplicationError(
                "No WhatsApp Business Accounts found for this code.",
                type="NO_WABA",
                non_retryable=True,
            )

        # 3. Choose which WABA (prefer the one the frontend captured).
        primary_waba = await workflow.execute_activity(
            select_primary_waba,
            SelectPrimaryWabaInput(
                waba_accounts=waba_accounts,
                preferred_waba_id=inp.preferred_waba_id,
            ),
            start_to_close_timeout=_TIMEOUT,
            retry_policy=_RETRY,
        )

        # 4. Grant the platform System User access (required before step 6).
        await workflow.execute_activity(
            assign_system_user,
            AssignSystemUserInput(waba_id=primary_waba.id, user_token=user_token),
            start_to_close_timeout=_TIMEOUT,
            retry_policy=_RETRY,
        )

        # 5. Subscribe webhook — non-fatal; log and continue if it fails
        try:
            await workflow.execute_activity(
                subscribe_waba_webhook,
                SubscribeWebhookInput(waba_id=primary_waba.id, user_token=user_token),
                start_to_close_timeout=_TIMEOUT,
                retry_policy=_SUBSCRIBE_RETRY,
            )
        except Exception:  # noqa: BLE001
            workflow.logger.warning(
                "webhook_subscription_failed",
                extra={"waba_id": primary_waba.id},
            )

        # 6. Share our Solution Partner credit line — non-fatal.
        allocation_config_id: str | None = None
        try:
            allocation_config_id = await workflow.execute_activity(
                share_credit_line,
                ShareCreditLineInput(
                    waba_id=primary_waba.id,
                    waba_currency=primary_waba.currency,
                ),
                start_to_close_timeout=_TIMEOUT,
                retry_policy=_SUBSCRIBE_RETRY,
            )
        except Exception:  # noqa: BLE001
            workflow.logger.warning(
                "credit_line_share_activity_failed",
                extra={"waba_id": primary_waba.id},
            )

        # 7. Fetch phone numbers under this WABA
        all_phone_numbers = await workflow.execute_activity(
            fetch_phone_numbers,
            FetchPhoneNumbersInput(waba_id=primary_waba.id, user_token=user_token),
            start_to_close_timeout=_TIMEOUT,
            retry_policy=_RETRY,
        )

        # 8. Register the primary phone number, if one was chosen
        # (FINISH_ONLY_WABA has none — still a success; status reflects it).
        primary_number = all_phone_numbers[0] if all_phone_numbers else None
        onboarding_status = OnboardingStatus.WABA_ONLY
        two_step_pin_encrypted: str | None = None

        if primary_number is not None:
            try:
                two_step_pin_encrypted = await workflow.execute_activity(
                    register_phone_number,
                    RegisterPhoneNumberInput(
                        phone_number_id=primary_number.id,
                        user_token=user_token,
                    ),
                    start_to_close_timeout=_TIMEOUT,
                    retry_policy=_RETRY,
                )
                onboarding_status = OnboardingStatus.COMPLETE

                # Optional smoke test — never affects onboarding_status.
                try:
                    await workflow.execute_activity(
                        send_test_message,
                        primary_number.id,
                        start_to_close_timeout=_TIMEOUT,
                        retry_policy=_SUBSCRIBE_RETRY,
                    )
                except Exception:  # noqa: BLE001
                    workflow.logger.warning(
                        "test_message_activity_failed",
                        extra={"phone_number_id": primary_number.id},
                    )
            except Exception:  # noqa: BLE001
                workflow.logger.warning(
                    "phone_number_registration_failed",
                    extra={"phone_number_id": primary_number.id},
                )
                onboarding_status = OnboardingStatus.PHONE_UNREGISTERED

        # 9. Attach WABA to the caller's tenant → returns TenantOnboardingResult
        result: TenantOnboardingResult = await workflow.execute_activity(
            register_tenant,
            RegisterTenantInput(
                tenant_id=inp.tenant_id,
                waba_id=primary_waba.id,
                display_name=primary_waba.name,
                onboarding_status=onboarding_status,
                phone_number_id=primary_number.id if primary_number else None,
                phone_number=(
                    primary_number.display_phone_number if primary_number else None
                ),
                all_phone_numbers=all_phone_numbers,
                two_step_pin_encrypted=two_step_pin_encrypted,
                allocation_config_id=allocation_config_id,
            ),
            start_to_close_timeout=_TIMEOUT,
            retry_policy=_RETRY,
        )

        return result
