"""
Auth route table. Registers the handlers from `endpoints` on a single auth
router. Response models are inferred from each handler's return annotation.
"""

from fastapi import APIRouter, status

from app.api.v1.auth import endpoints


auth_router = APIRouter(prefix="/auth", tags=["Auth"])

# --- OTP (phone/WhatsApp) ---
auth_router.add_api_route(
    "/otp/request",
    endpoints.request,
    methods=["POST"],
    status_code=status.HTTP_200_OK,
    summary="Send a signup or login verification code",
    description=(
        "Sends a WhatsApp OTP. An already-registered phone number gets a "
        "login code. A new one gets a signup code and requires "
        "business_name, first_name, and last_name — held pending in Redis "
        "until verify, nothing is written to the database yet."
    ),
)
auth_router.add_api_route(
    "/otp/verify",
    endpoints.verify,
    methods=["POST"],
    status_code=status.HTTP_200_OK,
    summary="Verify a code and complete signup or login",
    description=(
        "Verifies the code. If it carried pending signup data, creates the "
        "Tenant and its owner User atomically; otherwise completes a login "
        "for the existing User. Either way, returns access + refresh tokens."
    ),
)

# --- Email + password ---
auth_router.add_api_route(
    "/signup",
    endpoints.signup,
    methods=["POST"],
    status_code=status.HTTP_201_CREATED,
    summary="Sign up with email + password",
)
auth_router.add_api_route(
    "/login",
    endpoints.login,
    methods=["POST"],
    status_code=status.HTTP_200_OK,
    summary="Log in with email + password",
)
auth_router.add_api_route(
    "/refresh",
    endpoints.refresh,
    methods=["POST"],
    status_code=status.HTTP_200_OK,
    summary="Exchange a refresh token for a new token pair",
)
auth_router.add_api_route(
    "/me",
    endpoints.me,
    methods=["GET"],
    status_code=status.HTTP_200_OK,
    summary="Get the current authenticated user",
)

# --- WhatsApp Embedded Signup ---
auth_router.add_api_route(
    "/whatsapp/callback",
    endpoints.embedded_signup_callback,
    methods=["POST"],
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
