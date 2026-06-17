from fastapi import APIRouter, Request

from app.schemas.webhook import WhatsappWebhookResponse


router = APIRouter(prefix="/webhooks", tags=["webhook"])


@router.post("/whatsapp", response_model=WhatsappWebhookResponse)
async def whatsapp_webhook(request: Request):
    # Process the webhook response
    body = await request.json()

    return WhatsappWebhookResponse(
        id=body.get("id"), message=body.get("message"), phone=body.get("phone")
    )
