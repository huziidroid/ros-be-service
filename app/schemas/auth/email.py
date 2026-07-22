"""
Schemas for email+password signup, login, and token refresh.
"""

import re

from pydantic import BaseModel, field_validator


_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_MIN_PASSWORD_LENGTH = 8


def _validate_email(value: str) -> str:
    if not _EMAIL.match(value):
        raise ValueError("email is not a valid email address.")
    return value.lower()


def _validate_password(value: str) -> str:
    if len(value) < _MIN_PASSWORD_LENGTH:
        raise ValueError(
            f"password must be at least {_MIN_PASSWORD_LENGTH} characters."
        )
    return value


class EmailSignupRequestBody(BaseModel):
    business_name: str
    first_name: str
    last_name: str
    email: str
    password: str

    _validate_email = field_validator("email")(_validate_email)
    _validate_password = field_validator("password")(_validate_password)


class EmailLoginRequestBody(BaseModel):
    email: str
    password: str

    _validate_email = field_validator("email")(_validate_email)


class RefreshRequestBody(BaseModel):
    refresh_token: str
