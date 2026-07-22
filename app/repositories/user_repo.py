"""
User repository — async SQLAlchemy implementation.

Methods take an injected AsyncSession; callers commit/rollback after writes.
Uniqueness on email/phone_number is enforced by the DB (see migration 0003)
— create() lets IntegrityError propagate so callers can translate a race
(two concurrent signups for the same phone/email) into a clean 409 rather
than silently overwriting anything.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


class UserRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        tenant_id: uuid.UUID,
        first_name: str,
        last_name: str,
        email: str | None = None,
        phone_number: str | None = None,
        password_hash: str | None = None,
    ) -> User:
        """Insert a new user. Caller must commit the session after calling this."""
        user = User(
            tenant_id=tenant_id,
            first_name=first_name,
            last_name=last_name,
            email=email,
            phone_number=phone_number,
            password_hash=password_hash,
        )
        self.session.add(user)
        await self.session.flush()
        return user

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        result = await self.session.execute(
            select(User).where(User.id == user_id, User.is_active.is_(True))
        )
        return result.scalar_one_or_none()

    async def get_by_phone_number(self, phone_number: str) -> User | None:
        result = await self.session.execute(
            select(User).where(
                User.phone_number == phone_number, User.is_active.is_(True)
            )
        )
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        result = await self.session.execute(
            select(User).where(User.email == email, User.is_active.is_(True))
        )
        return result.scalar_one_or_none()
