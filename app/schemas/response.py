"""
Standard API response envelope — APIResponse[T]:
  {status_code, status: "success"|"error", message, data}

`status` is derived from status_code; build with ok() / err() / respond().
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
    """Generic response envelope; T narrows `data` in the OpenAPI docs."""

    status_code: int
    status: ResponseStatus
    message: str
    data: T | None = None


# --- Constructor helpers ---


def respond(
    *,
    status_code: int,
    message: str,
    data: Any = None,
) -> APIResponse[Any]:
    """Build an envelope, deriving `status` from `status_code`."""
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
