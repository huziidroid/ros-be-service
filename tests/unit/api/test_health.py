"""
Unit tests for the readiness probe's per-dependency check helpers
(app.api.v1.health.router._check_database/_check_redis/_check_temporal).

Each check is exercised in isolation with a minimal fake standing in for
the real dependency (AsyncSession/RedisClient/temporalio Client) — no live
Postgres, Redis, or Temporal needed.
"""

import pytest

from app.api.v1.health import router as health_router
from app.api.v1.health.router import _check_database, _check_redis, _check_temporal


class _FakeSession:
    def __init__(self, *, raises: bool = False) -> None:
        self._raises = raises

    async def execute(self, _stmt: object) -> None:
        if self._raises:
            raise ConnectionError("db unreachable")


class _FakeRedis:
    def __init__(self, *, healthy: bool = True) -> None:
        self._healthy = healthy

    async def ping(self) -> bool:
        if not self._healthy:
            raise ConnectionError("redis unreachable")
        return True


class TestCheckDatabase:
    async def test_ok_when_query_succeeds(self) -> None:
        assert await _check_database(_FakeSession()) == "ok"  # type: ignore[arg-type]

    async def test_unavailable_when_query_raises(self) -> None:
        result = await _check_database(_FakeSession(raises=True))  # type: ignore[arg-type]
        assert result == "unavailable"


class TestCheckRedis:
    async def test_ok_when_ping_succeeds(self) -> None:
        assert await _check_redis(_FakeRedis()) == "ok"  # type: ignore[arg-type]

    async def test_unavailable_when_ping_raises(self) -> None:
        result = await _check_redis(_FakeRedis(healthy=False))  # type: ignore[arg-type]
        assert result == "unavailable"


class TestCheckTemporal:
    async def test_unavailable_when_no_client(self) -> None:
        assert await _check_temporal(None) == "unavailable"

    async def test_ok_when_client_present_and_healthy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _healthy(*args: object, **kwargs: object) -> bool:
            return True

        monkeypatch.setattr(health_router, "check_temporal_health", _healthy)
        assert await _check_temporal(object()) == "ok"  # type: ignore[arg-type]

    async def test_unavailable_when_client_present_but_unhealthy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _unhealthy(*args: object, **kwargs: object) -> bool:
            return False

        monkeypatch.setattr(health_router, "check_temporal_health", _unhealthy)
        assert await _check_temporal(object()) == "unavailable"  # type: ignore[arg-type]
