from pydantic import BaseModel


class WhatsappWebhookResponse(BaseModel):
    id: str
    message: str
    phone: str
