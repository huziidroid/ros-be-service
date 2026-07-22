"""
Application exception hierarchy.

Domain and service layers raise these instead of FastAPI's HTTPException, so
lower layers stay framework-agnostic. app/api/exception_handlers.py maps any
AppError to the standard APIResponse envelope via its status_code/message.

status_code: HTTP status to return. message: client-safe text (never raw
exception text). internal_detail: server-side logging only, never sent to
the client.
"""

from __future__ import annotations


class AppError(Exception):
    """Base class for all application errors. Defaults to 500."""

    status_code: int = 500
    message: str = "Internal server error."

    def __init__(
        self,
        message: str | None = None,
        *,
        internal_detail: str | None = None,
    ) -> None:
        if message is not None:
            self.message = message
        self.internal_detail = internal_detail
        super().__init__(self.message)


class UnauthorizedError(AppError):
    """Missing, invalid, or expired credentials (401)."""

    status_code = 401
    message = "Authentication required."


class ConflictError(AppError):
    """Request conflicts with existing state, e.g. a duplicate signup (409)."""

    status_code = 409
    message = "This resource already exists."


class UnprocessableError(AppError):
    """Request was understood but cannot be fulfilled (422)."""

    status_code = 422
    message = "The request could not be processed."


class RateLimitedError(AppError):
    """Caller is retrying faster than allowed, e.g. OTP resend cooldown (429)."""

    status_code = 429
    message = "Please wait before trying again."


class UpstreamError(AppError):
    """A dependency (Meta, etc.) failed in a way we can't recover from (502)."""

    status_code = 502
    message = "An upstream service failed. Please try again."


class ServiceUnavailableError(AppError):
    """A required dependency is unavailable (503)."""

    status_code = 503
    message = "Service temporarily unavailable. Please try again shortly."
