"""
Tenant model — root entity for every distributor business.

A Tenant is created at signup (see app/services/auth.py), before any
WhatsApp connection exists — waba_id is NULL until the distributor
completes the optional, authenticated WhatsApp connect step
(app/api/v1/auth/whatsapp.py). Other models (Contact, Order, Message, etc.)
reference tenant_id → tenants.id.

phone_number_id is the webhook routing key Meta includes on every inbound
message. It can be NULL — no WABA connected yet, a FINISH_ONLY_WABA signup,
or a failed phone registration all leave it unset; onboarding_status (see
app.schemas.workflows.tenant_onboarding.OnboardingStatus) distinguishes
these states.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.schemas.workflows.tenant_onboarding import OnboardingStatus


class Tenant(Base):
    __tablename__ = "tenants"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Meta identifiers
    # unique=True intentionally omitted on both columns below: uniqueness is
    # enforced by a partial index (unique among is_active rows only — see
    # migration 0005), not by SQLAlchemy column metadata, so a deactivated
    # tenant doesn't permanently block reconnecting the same WABA/number.
    waba_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
        comment="WhatsApp Business Account ID from Meta. NULL until the "
        "distributor completes the optional WhatsApp connect step. Unique "
        "among active rows (ix_tenants_waba_id, migration 0005).",
    )
    phone_number_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
        comment="Primary phone number ID — webhook routing key. NULL until a "
        "phone number is chosen and registered (see onboarding_status). "
        "Unique among active rows (ix_tenants_phone_number_id, migration 0005).",
    )
    # Display
    display_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Business name — captured at signup; overwritten by the WABA's "
        "Meta display name if WhatsApp is later connected.",
    )
    phone_number: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        comment="Human-readable WhatsApp business number e.g. +923001234567 — "
        "NULL until WhatsApp is connected. Not the owner's login phone number; "
        "see User.phone_number for that.",
    )

    # Onboarding state
    onboarding_status: Mapped[OnboardingStatus] = mapped_column(
        SAEnum(
            OnboardingStatus,
            name="onboarding_status",
            # Bind the enum's lowercase .value ("not_connected"), matching the
            # Postgres type's labels — without this SQLAlchemy binds the member
            # name ("NOT_CONNECTED") and the insert fails.
            values_callable=lambda enum: [member.value for member in enum],
        ),
        nullable=False,
        default=OnboardingStatus.NOT_CONNECTED,
        server_default=OnboardingStatus.NOT_CONNECTED.value,
        comment="See app.schemas.workflows.tenant_onboarding.OnboardingStatus.",
    )
    two_step_pin: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
        comment="Cloud API two-step verification PIN, encrypted at rest "
        "(app.core.security). NULL until a phone number is registered.",
    )
    allocation_config_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="Solution Partner credit-sharing allocation config ID from "
        "Meta. NULL until share_credit_line succeeds.",
    )

    # Status
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<Tenant waba_id={self.waba_id} name={self.display_name!r}>"
