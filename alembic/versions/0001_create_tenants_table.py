"""create tenants table

Revision ID: 0001
Revises:
Create Date: 2026-06-24

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID


revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "waba_id",
            sa.String(length=64),
            nullable=False,
            comment="WhatsApp Business Account ID from Meta",
        ),
        sa.Column(
            "phone_number_id",
            sa.String(length=64),
            nullable=False,
            comment="Primary phone number ID — webhook routing key",
        ),
        sa.Column(
            "display_name",
            sa.String(length=255),
            nullable=False,
            comment="Business display name from Meta",
        ),
        sa.Column(
            "phone_number",
            sa.String(length=32),
            nullable=False,
            comment="Human-readable primary number e.g. +923001234567",
        ),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tenants_waba_id", "tenants", ["waba_id"], unique=True)
    op.create_index(
        "ix_tenants_phone_number_id", "tenants", ["phone_number_id"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_tenants_phone_number_id", table_name="tenants")
    op.drop_index("ix_tenants_waba_id", table_name="tenants")
    op.drop_table("tenants")
