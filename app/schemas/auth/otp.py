"""
Schemas for OTP-based (phone/WhatsApp) signup and login — one request/verify
pair, not two. Whether a phone number is signing up or logging in is
determined by whether it's already registered (see app/services/auth.py),
not by which endpoint the client called, so business_name/first_name/
last_name are only required the first time a number is ever seen.
"""

import re

from pydantic import BaseModel, field_validator


_E164 = re.compile(r"^\+[1-9]\d{6,14}$")


def _validate_phone_number(value: str) -> str:
    if not _E164.match(value):
        raise ValueError("phone_number must be in E.164 format, e.g. +923001234567.")
    return value


class OtpRequestBody(BaseModel):
    phone_number: str
    # Only required when phone_number isn't registered yet — see
    # app.services.auth.request_otp for the missing-field error.
    business_name: str | None = None
    first_name: str | None = None
    last_name: str | None = None

    _validate_phone_number = field_validator("phone_number")(_validate_phone_number)


class OtpVerifyRequestBody(BaseModel):
    phone_number: str
    code: str

    _validate_phone_number = field_validator("phone_number")(_validate_phone_number)


class OtpRequestedData(BaseModel):
    phone_number: str
    expires_in_seconds: int
