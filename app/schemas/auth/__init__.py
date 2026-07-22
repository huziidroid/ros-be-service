"""
Auth schemas.

Shared types live directly here (mirrors app.schemas.workflows): TokenPair,
UserSummary, and AuthResult are returned by every signup/login endpoint
below, so there's no single feature that owns them. Feature-specific
request bodies live in their own module, imported directly by callers:
  app.schemas.auth.whatsapp — Embedded Signup callback (WhatsApp connect,
                               an authenticated, optional post-signup step)
  app.schemas.auth.otp      — OTP (phone/WhatsApp) signup + login
  app.schemas.auth.email    — email + password signup + login + refresh
"""

from pydantic import BaseModel


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserSummary(BaseModel):
    id: str
    tenant_id: str
    first_name: str
    last_name: str
    email: str | None = None
    phone_number: str | None = None


class AuthResult(BaseModel):
    """Returned by every signup/login endpoint."""

    user: UserSummary
    tokens: TokenPair


__all__ = ["TokenPair", "UserSummary", "AuthResult"]
