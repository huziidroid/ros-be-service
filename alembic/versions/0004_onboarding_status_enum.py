"""onboarding_status becomes a native Postgres enum

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-13

tenants.onboarding_status was a String(32) documented by a comment listing
the allowed values (not_connected | complete | waba_only |
phone_unregistered) — those values also lived as four loose Python
constants (ONBOARDING_STATUS_*). Both now come from one place:
app.schemas.workflows.tenant_onboarding.OnboardingStatus. This migration
makes the DB enforce the same constraint the Python enum does, instead of
relying on application code never writing anything else.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_VALUES = ("not_connected", "complete", "waba_only", "phone_unregistered")
_ENUM_NAME = "onboarding_status"


def upgrade() -> None:
    onboarding_status_enum = postgresql.ENUM(*_VALUES, name=_ENUM_NAME)
    onboarding_status_enum.create(op.get_bind())

    op.execute("ALTER TABLE tenants ALTER COLUMN onboarding_status DROP DEFAULT")
    op.alter_column(
        "tenants",
        "onboarding_status",
        type_=onboarding_status_enum,
        existing_type=sa.String(length=32),
        postgresql_using="onboarding_status::onboarding_status",
    )
    op.execute(
        "ALTER TABLE tenants ALTER COLUMN onboarding_status "
        "SET DEFAULT 'not_connected'::onboarding_status"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE tenants ALTER COLUMN onboarding_status DROP DEFAULT")
    op.alter_column(
        "tenants",
        "onboarding_status",
        type_=sa.String(length=32),
        existing_type=postgresql.ENUM(*_VALUES, name=_ENUM_NAME),
        postgresql_using="onboarding_status::text",
    )
    op.execute(
        "ALTER TABLE tenants ALTER COLUMN onboarding_status SET DEFAULT 'not_connected'"
    )
    postgresql.ENUM(name=_ENUM_NAME).drop(op.get_bind())
