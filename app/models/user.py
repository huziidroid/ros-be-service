"""
User model — a person who can sign in to the platform.

Every user belongs to exactly one tenant (owner, created together with the
Tenant at signup — see app/services/auth.py). Sub-user invites (multiple
users per tenant, roles/permissions) are a deferred fast-follow; for now
every User is the tenant's owner.

A user authenticates via phone (OTP, no password) and/or email+password —
at least one identifier is required, enforced at the schema/service layer
rather than a DB constraint. phone_number and email are globally unique
(not just per-tenant): a person's phone number identifies one account
platform-wide, matching the "already registered" signup check.
"""

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TenantBase


class User(TenantBase):
    __tablename__ = "users"

    first_name: Mapped[str] = mapped_column(String(255), nullable=False)
    last_name: Mapped[str] = mapped_column(String(255), nullable=False)

    # unique=True intentionally omitted: uniqueness is enforced by a partial
    # index (unique among is_active rows only — see migration 0005), not by
    # SQLAlchemy column metadata, so a deactivated user doesn't permanently
    # block re-signup with the same email.
    email: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
        comment="NULL if the user has only ever signed up/logged in via OTP. "
        "Unique among active rows (ix_users_email, migration 0005).",
    )
    phone_number: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        index=True,
        comment="E.164 format e.g. +923001234567. NULL if the user signed up "
        "with email+password and has never verified a phone number. Unique "
        "among active rows (ix_users_phone_number, migration 0005).",
    )
    password_hash: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
        comment="Argon2 hash (app/core/passwords.py). NULL if the user has "
        "only ever authenticated via OTP.",
    )

    # Email verification is deferred (accounts are usable immediately after
    # signup for now) — this column exists so it can be wired up later
    # without another migration.
    email_verified: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} phone={self.phone_number} email={self.email}>"
