"""users table, tenant-first signup (waba_id nullable)

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-12

Supports the signup-first redesign: a Tenant is now created at signup,
before any WhatsApp connection exists, so waba_id must be nullable (it was
NOT NULL — WABA-first was the only path before this migration). WhatsApp
connect becomes an authenticated, optional step performed later.

Adds the users table — one owner user per tenant, authenticating via OTP
(phone) and/or email+password. Sub-user invites (multiple users per tenant)
are a deferred fast-follow.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("tenants", "waba_id", nullable=True)
    op.alter_column(
        "tenants",
        "onboarding_status",
        server_default="not_connected",
    )

    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("first_name", sa.String(length=255), nullable=False),
        sa.Column("last_name", sa.String(length=255), nullable=False),
        sa.Column(
            "email",
            sa.String(length=255),
            nullable=True,
            comment="NULL if the user has only ever signed up/logged in via OTP.",
        ),
        sa.Column(
            "phone_number",
            sa.String(length=32),
            nullable=True,
            comment="E.164 format e.g. +923001234567.",
        ),
        sa.Column(
            "password_hash",
            sa.String(length=512),
            nullable=True,
            comment="Argon2 hash. NULL if the user has only ever used OTP.",
        ),
        sa.Column(
            "email_verified",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_phone_number", "users", ["phone_number"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_phone_number", table_name="users")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_index("ix_users_tenant_id", table_name="users")
    op.drop_table("users")

    op.alter_column(
        "tenants",
        "onboarding_status",
        server_default="complete",
    )
    # NOTE: reverting to NOT NULL will fail if any row has a NULL waba_id
    # (any tenant created via signup that never connected WhatsApp) —
    # backfill or delete those rows before downgrading in an environment
    # with real data.
    op.alter_column("tenants", "waba_id", nullable=False)
