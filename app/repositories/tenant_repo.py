"""
Tenant repository — async SQLAlchemy implementation.

Methods take an injected AsyncSession; callers commit/rollback after writes.

create_pending() creates the tenant row at signup, before any WhatsApp
connection exists. attach_waba() is the later, authenticated connect step —
it updates that same row by tenant_id rather than upserting by waba_id,
since the row already exists with waba_id still NULL (an ON CONFLICT on
waba_id would never match it and would insert an orphaned duplicate row
instead). attach_waba() also pre-checks both waba_id and phone_number_id
for cross-tenant collisions, so a WABA or number already connected
elsewhere surfaces as a clean ConflictError instead of a raw IntegrityError.
"""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError
from app.models.tenant import Tenant
from app.schemas.workflows.tenant_onboarding import OnboardingStatus


class TenantRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_pending(self, *, display_name: str) -> Tenant:
        """
        Create a tenant at signup, before any WhatsApp connection exists.

        Caller must commit the session after calling this method (typically
        as part of the same transaction that creates the owner User — see
        app/services/auth.py).
        """
        tenant = Tenant(
            display_name=display_name,
            onboarding_status=OnboardingStatus.NOT_CONNECTED,
        )
        self.session.add(tenant)
        await self.session.flush()
        return tenant

    async def attach_waba(
        self,
        *,
        tenant_id: UUID,
        waba_id: str,
        display_name: str,
        onboarding_status: OnboardingStatus,
        phone_number_id: str | None = None,
        phone_number: str | None = None,
        two_step_pin_encrypted: str | None = None,
        allocation_config_id: str | None = None,
    ) -> Tenant:
        """
        Attach a WABA to an existing (signup-created) tenant.

        Caller must commit the session after calling this method.

        Raises ConflictError if the WABA or phone number is already
        connected to a *different* tenant — pre-checked here, and also
        guarded against an IntegrityError from a concurrent request racing
        this one, so the client never sees a raw SQL error.
        """
        existing_by_waba = await self.get_by_waba_id(waba_id)
        if existing_by_waba is not None and existing_by_waba.id != tenant_id:
            raise ConflictError(
                "This WhatsApp Business Account is already connected to "
                "another Retail OS account."
            )

        if phone_number_id is not None:
            existing_by_phone = await self.get_by_phone_number_id(phone_number_id)
            if existing_by_phone is not None and existing_by_phone.id != tenant_id:
                raise ConflictError(
                    "This WhatsApp number is already connected to another "
                    "Retail OS account."
                )

        values: dict[str, object] = {
            "waba_id": waba_id,
            "display_name": display_name,
            "onboarding_status": onboarding_status,
            "phone_number_id": phone_number_id,
            "phone_number": phone_number,
            "updated_at": datetime.now(UTC),
        }
        if two_step_pin_encrypted is not None:
            values["two_step_pin"] = two_step_pin_encrypted
        if allocation_config_id is not None:
            values["allocation_config_id"] = allocation_config_id

        try:
            result = await self.session.execute(
                update(Tenant)
                .where(Tenant.id == tenant_id)
                .values(**values)
                .returning(Tenant)
            )
        except IntegrityError as exc:
            raise ConflictError(
                "This WhatsApp Business Account or number is already "
                "connected to another Retail OS account.",
                internal_detail=str(exc),
            ) from exc
        return result.scalar_one()

    async def get_by_id(self, tenant_id: UUID) -> Tenant | None:
        result = await self.session.execute(
            select(Tenant).where(Tenant.id == tenant_id, Tenant.is_active.is_(True))
        )
        return result.scalar_one_or_none()

    async def get_by_phone_number_id(self, phone_number_id: str) -> Tenant | None:
        """Look up the tenant whose primary phone_number_id matches."""
        result = await self.session.execute(
            select(Tenant).where(
                Tenant.phone_number_id == phone_number_id,
                Tenant.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def get_by_waba_id(self, waba_id: str) -> Tenant | None:
        result = await self.session.execute(
            select(Tenant).where(
                Tenant.waba_id == waba_id,
                Tenant.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none()

    # -----------------------------------------------------------------------
    # Reconciliation — retry queues for the two onboarding steps that are
    # allowed to fail non-fatally (see app.workflows.tenant_reconciliation)
    # -----------------------------------------------------------------------

    async def list_needing_credit_share(self) -> list[Tenant]:
        """
        Active tenants with a connected WABA whose Solution Partner credit
        line was never confirmed shared. waba_id IS NOT NULL excludes
        tenants that signed up but haven't connected WhatsApp yet — there's
        no WABA to share credit with until they do.
        """
        result = await self.session.execute(
            select(Tenant).where(
                Tenant.waba_id.is_not(None),
                Tenant.allocation_config_id.is_(None),
                Tenant.is_active.is_(True),
            )
        )
        return list(result.scalars())

    async def list_needing_phone_registration(self) -> list[Tenant]:
        """Active tenants whose phone number was chosen but never registered for Cloud API."""
        result = await self.session.execute(
            select(Tenant).where(
                Tenant.onboarding_status == OnboardingStatus.PHONE_UNREGISTERED,
                Tenant.is_active.is_(True),
            )
        )
        return list(result.scalars())

    async def mark_credit_shared(
        self, *, waba_id: str, allocation_config_id: str
    ) -> None:
        """Caller must commit the session after calling this method."""
        await self.session.execute(
            update(Tenant)
            .where(Tenant.waba_id == waba_id)
            .values(
                allocation_config_id=allocation_config_id, updated_at=datetime.now(UTC)
            )
        )

    async def mark_phone_registered(
        self, *, waba_id: str, two_step_pin_encrypted: str
    ) -> None:
        """Caller must commit the session after calling this method."""
        await self.session.execute(
            update(Tenant)
            .where(Tenant.waba_id == waba_id)
            .values(
                two_step_pin=two_step_pin_encrypted,
                onboarding_status=OnboardingStatus.COMPLETE,
                updated_at=datetime.now(UTC),
            )
        )
