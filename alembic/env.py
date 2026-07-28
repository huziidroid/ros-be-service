"""
Alembic env.py — async SQLAlchemy configuration.

Uses asyncio.run() + AsyncEngine so autogenerate works with async models.
Database URL is read from app settings (DATABASE_URL env var).
"""

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine

# Import all models so Alembic can see them for autogenerate.
# Add new model imports here as new models are created.
from app.models.base import Base  # noqa: F401
from app.models.tenant import Tenant  # noqa: F401
from app.models.user import User  # noqa: F401


# Load .env so DATABASE_URL is available when running alembic from the CLI.
# In production (env vars already set by the platform) this is a no-op.
load_dotenv()


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _get_database_url() -> str:
    """
    Resolve the database URL without instantiating the full Settings object.

    This avoids requiring all required env vars (WhatsApp secrets, SECRET_KEY, etc.)
    to be present just to run a migration — only DATABASE_URL is needed.
    """
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL environment variable is not set.")
    if not url.startswith("postgresql+asyncpg://"):
        raise RuntimeError("DATABASE_URL must use the postgresql+asyncpg:// driver.")
    return url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (no DB connection — outputs SQL)."""
    url = _get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):  # type: ignore[no-untyped-def]
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,  # detect column type changes
        compare_server_default=True,  # detect server_default changes
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations in 'online' mode using an async engine."""
    engine = create_async_engine(_get_database_url())
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
