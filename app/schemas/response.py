"""
Standard API response envelope.

Every endpoint returns APIResponse[T]:
  {
    "status_code": 200,
    "status":      "success" | "error",
    "message":     "Human-readable summary",
    "data":        <payload> | null
  }

Usage in route handlers:
  return ok(data=MySchema(...), message="Created.")
  return ok(data=MySchema(...), message="Created.", status_code=201)

Global exception handlers (app/api/exception_handlers.py) map HTTPException
and validation errors to this same shape.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Generic, TypeVar

from pydantic import BaseModel


T = TypeVar("T")


class ResponseStatus(StrEnum):
    """APIResponse.status — derived from status_code, never set directly by callers."""

    SUCCESS = "success"
    ERROR = "error"


class APIResponse(BaseModel, Generic[T]):
    """
    Generic response envelope used by every endpoint.

    Type parameter T narrows the shape of `data` in generated OpenAPI docs.
    """

    status_code: int
    status: ResponseStatus
    message: str
    data: T | None = None


# ---------------------------------------------------------------------------
# Constructor helpers — use these in route handlers
# ---------------------------------------------------------------------------


def respond(
    *,
    status_code: int,
    message: str,
    data: Any = None,
) -> APIResponse[Any]:
    """
    Build an envelope, deriving `status` from `status_code` — callers never
    set "success"/"error" by hand, so the two can't disagree.
    """
    status = ResponseStatus.SUCCESS if status_code < 400 else ResponseStatus.ERROR
    return APIResponse(
        status_code=status_code, status=status, message=message, data=data
    )


def ok(
    data: T | None = None,
    message: str = "",
    status_code: int = 200,
) -> APIResponse[T]:
    """Success response. `status` is derived from `status_code` (see respond)."""
    return respond(status_code=status_code, message=message, data=data)


def err(
    message: str,
    data: Any = None,
    status_code: int = 400,
) -> APIResponse[Any]:
    """Error response body (used by global exception handlers)."""
    return respond(status_code=status_code, message=message, data=data)
