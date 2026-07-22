"""uniqueness on soft-deletable columns becomes WHERE is_active

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-12

users.email, users.phone_number, tenants.waba_id, and tenants.phone_number_id
are each unique across ALL rows today, but every read already filters
is_active = true (UserRepo, TenantRepo). There's no deactivation flow yet,
so this is preventative: the moment one exists, a deactivated row would
permanently block re-signup/re-connect with the same email, phone number,
WABA, or phone_number_id. Converting these to partial unique indexes (unique
only among active rows) fixes that ahead of time, with no behavior change
for the current all-active-rows world.

No application code changes needed — SQLAlchemy's unique=True is dropped
from the model columns in this same change (index=True is kept for lookup
performance); the actual uniqueness constraint now lives only here, in the
partial index, not in ORM column metadata.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_INDEXES = [
    # (index_name, table, column)
    ("ix_users_email", "users", "email"),
    ("ix_users_phone_number", "users", "phone_number"),
    ("ix_tenants_waba_id", "tenants", "waba_id"),
    ("ix_tenants_phone_number_id", "tenants", "phone_number_id"),
]


def upgrade() -> None:
    for name, table, column in _INDEXES:
        op.drop_index(name, table_name=table)
        op.create_index(
            name,
            table,
            [column],
            unique=True,
            postgresql_where=sa.text("is_active = true"),
        )


def downgrade() -> None:
    for name, table, column in _INDEXES:
        op.drop_index(name, table_name=table)
        op.create_index(name, table, [column], unique=True)
