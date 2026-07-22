import asyncio
import logging
from datetime import timedelta

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from temporalio.client import Client

from app.api.dependencies import RedisDep, SessionDep
from app.clients.redis import RedisClient
from app.clients.temporal import check_health as check_temporal_health
from app.schemas.health import HealthCheckData, ReadinessData
from app.schemas.response import APIResponse, ok, respond


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["health"])

_CHECK_TIMEOUT_SECONDS = 3


@router.get("/live", response_model=APIResponse[HealthCheckData])
async def live() -> APIResponse[HealthCheckData]:
    """Liveness probe — confirms the process is running."""
    return ok(data=HealthCheckData(), message="Service is live.")


async def _check_database(session: AsyncSession) -> str:
    try:
        await asyncio.wait_for(
            session.execute(text("SELECT 1")), timeout=_CHECK_TIMEOUT_SECONDS
        )
        return "ok"
    except Exception as exc:  # noqa: BLE001 — health checks report status, never raise
        logger.warning("readiness_check_database_failed", extra={"error": str(exc)})
        return "unavailable"


async def _check_redis(redis: RedisClient) -> str:
    try:
        healthy = await asyncio.wait_for(redis.ping(), timeout=_CHECK_TIMEOUT_SECONDS)
    except Exception as exc:  # noqa: BLE001 — health checks report status, never raise
        logger.warning("readiness_check_redis_failed", extra={"error": str(exc)})
        return "unavailable"
    return "ok" if healthy else "unavailable"


async def _check_temporal(client: Client | None) -> str:
    if client is None:
        return "unavailable"
    healthy = await check_temporal_health(
        client, rpc_timeout=timedelta(seconds=_CHECK_TIMEOUT_SECONDS)
    )
    return "ok" if healthy else "unavailable"


@router.get("/ready")
async def ready(request: Request, session: SessionDep, redis: RedisDep) -> JSONResponse:
    """
    Readiness probe. Actively checks Postgres, Redis, and Temporal — not
    just that a client object exists. Returns 200 if all checks pass, 503
    otherwise. Extend checks{} as more deps are added.
    """
    temporal_client = getattr(request.app.state, "temporal", None)

    db_status, redis_status, temporal_status = await asyncio.gather(
        _check_database(session),
        _check_redis(redis),
        _check_temporal(temporal_client),
    )
    checks = {
        "database": db_status,
        "redis": redis_status,
        "temporal": temporal_status,
    }

    all_ready = all(v == "ok" for v in checks.values())
    http_status = 200 if all_ready else 503

    if not all_ready:
        logger.warning("readiness_check_failed", extra={"checks": checks})

    # respond() derives status from status_code, so a 503 is never labelled "success".
    response = respond(
        status_code=http_status,
        message="Service is ready." if all_ready else "Some dependencies unavailable.",
        data=ReadinessData(ready=all_ready, checks=checks),
    )
    return JSONResponse(status_code=http_status, content=response.model_dump())
