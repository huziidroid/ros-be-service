"""
Embedded Signup callback endpoint — the "connect WhatsApp" step.

An authenticated, optional step performed after signup (see
app/services/auth.py) — not part of login. The tenant row already exists
by the time this runs; the workflow attaches the WABA to it instead of
creating a new tenant.

Flow:
  1. Distributor signs up (OTP or email+password) and is authenticated.
  2. From their dashboard, they complete Meta Embedded Signup.
  3. Frontend POSTs the short-lived `code` (FB.login callback) plus the
     WA_EMBEDDED_SIGNUP session event (event type + ids, or CANCEL/ERROR),
     with the distributor's own access token in the Authorization header.
  4. If the event shows the flow didn't succeed, or there's no code, we log
     and return without calling Meta — nothing to exchange.
  5. Otherwise the onboarding service runs TenantOnboardingWorkflow
     synchronously and we wait for the result.
  6. The workflow exchanges the code, selects the WABA, shares our Solution
     Partner credit line, registers the primary phone number, and attaches
     the WABA to the caller's tenant. onboarding_status tells the frontend
     the outcome even when no phone number was chosen or registration
     failed.
  7. We return the updated tenant summary.
"""

import logging

from fastapi import APIRouter, status

from app.api.dependencies import CurrentUserDep, TemporalDep
from app.schemas.auth.whatsapp import (
    EmbeddedSignupCallbackRequest,
    EmbeddedSignupOutcome,
    RegisteredPhoneNumber,
    TenantOnboardingData,
)
from app.schemas.response import APIResponse, ok
from app.services.onboarding import run_tenant_onboarding


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/whatsapp", tags=["Auth"])

# Event values meaning Embedded Signup genuinely completed — anything else
# (CANCEL, ERROR, unrecognized) means the customer didn't finish. See
# https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/implementation#session-logging-message-event-listener
_SUCCESS_EVENTS = {
    "FINISH",
    "FINISH_ONLY_WABA",
    "FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING",
    "FINISH_OBO_MIGRATION",
    "FINISH_GRANT_ONLY_API_ACCESS",
}


@router.post(
    "/callback",
    response_model=APIResponse[TenantOnboardingData],
    status_code=status.HTTP_200_OK,
    summary="Handle Embedded Signup callback",
    description=(
        "Authenticated. Exchange the Embedded Signup `code` for a user "
        "access token, discover/select the distributor's WABA, share our "
        "Solution Partner credit line, discover phone numbers, register the "
        "primary one for Cloud API use, and attach the WABA to the caller's "
        "tenant. Short-circuits without calling Meta if `event` indicates "
        "the customer cancelled or errored out of the flow. Runs "
        "synchronously via Temporal — the response reflects the final "
        "onboarding state."
    ),
)
async def embedded_signup_callback(
    body: EmbeddedSignupCallbackRequest,
    temporal: TemporalDep,
    current_user: CurrentUserDep,
) -> APIResponse[TenantOnboardingData]:
    if not body.code:
        logger.info(
            "embedded_signup_no_code",
            extra={"event": body.event, "current_step": body.current_step},
        )
        return ok(
            data=TenantOnboardingData(
                status=EmbeddedSignupOutcome.ERROR
                if body.error_code
                else EmbeddedSignupOutcome.CANCELLED
            ),
            message="Embedded Signup did not complete — no code to exchange.",
        )

    if body.event is not None and body.event not in _SUCCESS_EVENTS:
        # Meta sometimes issues a code even on non-success paths, but the
        # event says the customer didn't finish — don't burn a single-use
        # code on an abandoned or errored signup.
        logger.warning(
            "embedded_signup_not_successful",
            extra={
                "event": body.event,
                "current_step": body.current_step,
                "error_code": body.error_code,
                "error_message": body.error_message,
            },
        )
        outcome = (
            EmbeddedSignupOutcome.ERROR
            if (body.error_code or body.event == "ERROR")
            else EmbeddedSignupOutcome.CANCELLED
        )
        return ok(
            data=TenantOnboardingData(status=outcome),
            message="Embedded Signup was not completed successfully.",
        )

    # Temporal errors → typed AppError happens in the service; the global
    # handler turns those into the standard envelope.
    result = await run_tenant_onboarding(
        temporal,
        code=body.code,
        tenant_id=str(current_user.tenant_id),
        preferred_waba_id=body.waba_id,
    )

    return ok(
        data=TenantOnboardingData(
            status=EmbeddedSignupOutcome.REGISTERED,
            waba_id=result.waba_id,
            display_name=result.display_name,
            onboarding_status=result.onboarding_status,
            credit_shared=result.credit_shared,
            phone_numbers=[
                RegisteredPhoneNumber(
                    phone_number_id=pn.id,
                    display_phone_number=pn.display_phone_number,
                    verified_name=pn.verified_name,
                    status=pn.status,
                )
                for pn in result.phone_numbers
            ],
        ),
        message="Tenant registered successfully.",
    )
