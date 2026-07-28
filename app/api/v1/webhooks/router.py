"""
Webhook route table. Response models are inferred from each handler's return
annotation.
"""

from fastapi import APIRouter

from app.api.v1.webhooks import endpoints


router = APIRouter(prefix="/webhooks")

router.add_api_route(
    "/whatsapp",
    endpoints.verify_webhook,
    methods=["GET"],
    tags=["WhatsApp Webhooks"],
)
router.add_api_route(
    "/whatsapp",
    endpoints.whatsapp_webhook,
    methods=["POST"],
    tags=["WhatsApp Webhooks"],
)
