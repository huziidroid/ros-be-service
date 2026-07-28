"""
Pydantic schemas for the Meta WhatsApp Cloud API webhook payload.

Every event (inbound messages + delivery statuses) POSTs the same envelope:
object → entry[] → changes[] → value → messages[] | statuses[].
"""

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


# --- Message-type-specific payloads ---


class TextPayload(BaseModel):
    body: str


class MediaPayload(BaseModel):
    """Shared structure for audio, image, video, document, sticker."""

    id: str  # Media ID — download via the Media API
    mime_type: str | None = None
    sha256: str | None = None
    caption: str | None = None  # image / video only


class LocationPayload(BaseModel):
    latitude: float
    longitude: float
    name: str | None = None
    address: str | None = None


class ButtonPayload(BaseModel):
    """Quick-reply button click on a template message."""

    payload: str
    text: str


class InteractiveListReply(BaseModel):
    id: str
    title: str
    description: str | None = None


class InteractiveButtonReply(BaseModel):
    id: str
    title: str


class InteractivePayload(BaseModel):
    type: Literal["list_reply", "button_reply"]
    list_reply: InteractiveListReply | None = None
    button_reply: InteractiveButtonReply | None = None


class ReactionPayload(BaseModel):
    message_id: str
    emoji: str


class ContactProfile(BaseModel):
    name: str


# --- Top-level message object ---


class InboundMessage(BaseModel):
    """A single inbound message inside value.messages[]."""

    id: str  # wamid — idempotency / dedup key
    from_: str = Field(alias="from")  # sender wa_id (E.164, no +)
    timestamp: str
    type: str  # text | audio | image | video | document | location | button | interactive | reaction

    # Type-specific payloads — only one is present per message.
    text: TextPayload | None = None
    audio: MediaPayload | None = None
    image: MediaPayload | None = None
    video: MediaPayload | None = None
    document: MediaPayload | None = None
    sticker: MediaPayload | None = None
    location: LocationPayload | None = None
    button: ButtonPayload | None = None
    interactive: InteractivePayload | None = None
    reaction: ReactionPayload | None = None

    model_config = {"populate_by_name": True}

    @property
    def text_body(self) -> str | None:
        """Extract text regardless of message type."""
        if self.type == "text" and self.text:
            return self.text.body
        if self.type == "button" and self.button:
            return self.button.text
        if self.type == "interactive" and self.interactive:
            if self.interactive.list_reply:
                return self.interactive.list_reply.title
            if self.interactive.button_reply:
                return self.interactive.button_reply.title
        return None

    @property
    def media_id(self) -> str | None:
        """Extract the media ID for downloadable types."""
        media = self.audio or self.image or self.video or self.document or self.sticker
        return media.id if media else None


# --- Delivery status (acknowledged, unused) ---


class MessageDeliveryStatus(StrEnum):
    """Meta's delivery statuses; unrecognized values map to UNKNOWN via _missing_."""

    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"
    DELETED = "deleted"
    WARNING = "warning"
    UNKNOWN = "unknown"

    @classmethod
    def _missing_(cls, value: object) -> "MessageDeliveryStatus":  # noqa: ARG003 — Enum hook signature
        return cls.UNKNOWN


class MessageStatus(BaseModel):
    id: str
    status: MessageDeliveryStatus
    timestamp: str
    recipient_id: str
    errors: list[dict[str, Any]] | None = None


# --- Webhook envelope ---


class WebhookContact(BaseModel):
    """Sender profile info, parallel to messages[]."""

    profile: ContactProfile
    wa_id: str


class WebhookMetadata(BaseModel):
    display_phone_number: str
    phone_number_id: str


class WebhookValue(BaseModel):
    messaging_product: str
    metadata: WebhookMetadata
    contacts: list[WebhookContact] | None = None
    messages: list[InboundMessage] | None = None
    statuses: list[MessageStatus] | None = None


class WebhookChange(BaseModel):
    value: WebhookValue
    field: str  # "messages" for all message + status events


class WebhookEntry(BaseModel):
    id: str  # WABA ID
    changes: list[WebhookChange]


class WhatsAppWebhookPayload(BaseModel):
    """Root envelope for every webhook POST from Meta."""

    object: str  # always "whatsapp_business_account"
    entry: list[WebhookEntry]


# --- Webhook endpoint response ---


class WebhookAckData(BaseModel):
    workflows_started: int
