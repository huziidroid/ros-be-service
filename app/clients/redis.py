"""
Redis client — ephemeral state only (OTP codes, pending-signup data,
resend cooldowns — see app/services/otp.py). Never a system of
record; every key we write carries a TTL and is safe to lose.

Mirrors app/clients/whatsapp.py as "the module that owns talking to an
external service" — here that service is Redis rather than the Meta Graph
API, so the surface is a thin, purpose-built wrapper (get/set/delete/exists
/ttl) instead of a general-purpose client passthrough.
"""

from collections.abc import AsyncGenerator
from typing import cast

from redis.asyncio import Redis, from_url

from app.core.settings import settings


class RedisClient:
    def __init__(self, url: str) -> None:
        self._redis: Redis = from_url(url, decode_responses=True)

    async def get(self, key: str) -> str | None:
        # redis-py's stubs type .get() as bytes | str | None unconditionally
        # — they can't see decode_responses=True above, which is what
        # actually makes this str | None at runtime, always.
        return cast("str | None", await self._redis.get(key))

    async def set(self, key: str, value: str, *, ex: int | None = None) -> None:
        await self._redis.set(key, value, ex=ex)

    async def delete(self, key: str) -> None:
        await self._redis.delete(key)

    async def exists(self, key: str) -> bool:
        return bool(await self._redis.exists(key))

    async def ttl(self, key: str) -> int:
        """Seconds until `key` expires, or a negative value if it's missing/has no TTL."""
        return await self._redis.ttl(key)

    async def ping(self) -> bool:
        """True if Redis responds. False on any connection error."""
        try:
            return bool(await self._redis.ping())
        except Exception:  # noqa: BLE001 — health checks report status, never raise
            return False

    async def close(self) -> None:
        await self._redis.aclose()


redis_client = RedisClient(settings.redis_url)


async def get_redis_client() -> AsyncGenerator[RedisClient, None]:
    """FastAPI dependency — yields the shared RedisClient."""
    yield redis_client
