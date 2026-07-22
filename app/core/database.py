"""
Async SQLAlchemy engine and session factory.

Activities manage their own session:
    async with AsyncSessionLocal() as session:
        repo = TenantRepo(session)
        await session.commit()

Routes inject one via SessionDep (app/api/dependencies.py):
    async def my_route(session: SessionDep) -> ...: ...
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.settings import settings


engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,  # logs SQL in dev; off in prod
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,  # drop stale connections before use
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,  # keep ORM objects usable after commit
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency — yields an AsyncSession per request."""
    async with AsyncSessionLocal() as session:
        yield session
