"""
Tenant repository — async SQLAlchemy. Methods take an injected AsyncSession;
callers commit/rollback. create_pending() makes the row at signup; attach_waba()
later connects a WABA (updating by tenant_id) and rejects cross-tenant
collisions with ConflictError.
"""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError
from app.core.settings import settings
from app.models.tenant import Tenant
from app.schemas.workflows.tenant_onboarding import OnboardingStatus


class TenantRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_pending(self, *, display_name: str) -> Tenant:
        """Create a tenant at signup, before any WhatsApp connection. Caller commits."""
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
        Attach a WABA to an existing tenant. Caller commits. ConflictError if
        the WABA/number is already connected to a different tenant.
        """
        existing_by_waba = await self.get_by_waba_id(waba_id)
        if existing_by_waba is not None and existing_by_waba.id != tenant_id:
            raise ConflictError(
                "This WhatsApp Business Account is already connected to "
                f"another {settings.app_name} account."
            )

        if phone_number_id is not None:
            existing_by_phone = await self.get_by_phone_number_id(phone_number_id)
            if existing_by_phone is not None and existing_by_phone.id != tenant_id:
                raise ConflictError(
                    "This WhatsApp number is already connected to another "
                    f"{settings.app_name} account."
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
                f"connected to another {settings.app_name} account.",
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

    # --- Reconciliation: retry queues for non-fatal onboarding steps ---

    async def list_needing_credit_share(self) -> list[Tenant]:
        """Active tenants with a connected WABA whose credit line was never confirmed shared."""
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
