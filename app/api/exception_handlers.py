"""
Global FastAPI exception handlers, registered via register_exception_handlers
in main.py. Every error — application, HTTP, validation, or unexpected —
returns the standard APIResponse envelope; clients never see a bare
{"detail": "..."} body.

Handlers (most specific first):
  AppError                 → its own status_code + client-safe message
  WhatsAppAPIError          → 502, upstream messaging provider failed
  RateLimitExceeded         → 429, same message as AppError's RateLimitedError
  StarletteHTTPException   → status_code + detail
  RequestValidationError   → 422 with a flattened field summary
  Exception (catch-all)    → 500 generic message (detail logged, not sent)
"""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.clients.whatsapp import WhatsAppAPIError
from app.core.exceptions import AppError, RateLimitedError, UpstreamError
from app.schemas.response import err


logger = logging.getLogger(__name__)


def _envelope(status_code: int, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=err(message=message, status_code=status_code).model_dump(),
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        # internal_detail is for us; message is the client-safe text.
        logger.warning(
            "app_error",
            extra={
                "status_code": exc.status_code,
                "error_type": exc.__class__.__name__,
                "detail": exc.internal_detail or exc.message,
                "path": request.url.path,
            },
        )
        return _envelope(exc.status_code, exc.message)

    @app.exception_handler(WhatsAppAPIError)
    async def whatsapp_api_error_handler(
        request: Request, exc: WhatsAppAPIError
    ) -> JSONResponse:
        # A non-2xx from Meta's Graph API — our upstream failed, so this is a
        # 502, not a 500. Log Meta's real status/body; return a safe message.
        logger.error(
            "whatsapp_upstream_error",
            extra={
                "meta_status": exc.status_code,
                "detail": str(exc),
                "path": request.url.path,
            },
        )
        return _envelope(
            UpstreamError.status_code,
            "Couldn't send the WhatsApp message right now. Please try again.",
        )

    @app.exception_handler(RateLimitExceeded)
    async def rate_limit_exceeded_handler(
        request: Request,
        exc: RateLimitExceeded,  # noqa: ARG001 — detail already logged by slowapi
    ) -> JSONResponse:
        response = _envelope(RateLimitedError.status_code, RateLimitedError.message)
        # Adds the X-RateLimit-* / Retry-After headers so clients can read
        # limit/remaining regardless of which handler produced the response.
        injected: JSONResponse = request.app.state.limiter._inject_headers(
            response, request.state.view_rate_limit
        )
        return injected

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request,  # noqa: ARG001 — required by FastAPI handler signature
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        return _envelope(exc.status_code, str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request,  # noqa: ARG001 — required by FastAPI handler signature
        exc: RequestValidationError,
    ) -> JSONResponse:
        messages = "; ".join(
            f"{' → '.join(str(loc) for loc in e['loc'])}: {e['msg']}"
            for e in exc.errors()
        )
        return _envelope(422, messages)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        # Log the full traceback; return a stable, generic message to the client.
        logger.exception(
            "unhandled_exception",
            extra={"path": request.url.path, "error_type": exc.__class__.__name__},
        )
        return _envelope(500, "Internal server error.")
