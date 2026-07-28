"""
Health route table. Response models are inferred from each handler's return
annotation.
"""

from fastapi import APIRouter

from app.api.v1.health import endpoints


router = APIRouter(prefix="/health", tags=["health"])

router.add_api_route("/live", endpoints.live, methods=["GET"])
router.add_api_route("/ready", endpoints.ready, methods=["GET"])
