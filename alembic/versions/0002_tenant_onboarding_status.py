"""tenant onboarding status, two-step pin, credit sharing

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-10

Supports:
  - FINISH_ONLY_WABA Embedded Signup completions (no phone number chosen) —
    phone_number_id / phone_number become nullable, tracked via
    onboarding_status instead of being rejected outright.
  - Cloud API phone number registration — two_step_pin stores the encrypted
    two-step verification PIN (app.core.security).
  - Solution Partner credit sharing — allocation_config_id records Meta's
    confirmation that our extended credit line is shared with the tenant's WABA.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("tenants", "phone_number_id", nullable=True)
    op.alter_column("tenants", "phone_number", nullable=True)

    op.add_column(
        "tenants",
        sa.Column(
            "onboarding_status",
            sa.String(length=32),
            nullable=False,
            server_default="complete",
            comment="complete | waba_only | phone_unregistered",
        ),
    )
    op.add_column(
        "tenants",
        sa.Column(
            "two_step_pin",
            sa.String(length=512),
            nullable=True,
            comment="Encrypted Cloud API two-step verification PIN",
        ),
    )
    op.add_column(
        "tenants",
        sa.Column(
            "allocation_config_id",
            sa.String(length=64),
            nullable=True,
            comment="Solution Partner credit-sharing allocation config ID from Meta",
        ),
    )


def downgrade() -> None:
    op.drop_column("tenants", "allocation_config_id")
    op.drop_column("tenants", "two_step_pin")
    op.drop_column("tenants", "onboarding_status")

    # NOTE: reverting to NOT NULL will fail if any row has a NULL
    # phone_number_id/phone_number (e.g. a waba_only tenant) — backfill or
    # delete those rows before downgrading in an environment with real data.
    op.alter_column("tenants", "phone_number", nullable=False)
    op.alter_column("tenants", "phone_number_id", nullable=False)
