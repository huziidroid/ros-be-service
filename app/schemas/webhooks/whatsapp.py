"""
Pydantic schemas for the Meta WhatsApp Cloud API webhook payload.

Meta sends all events (inbound messages + delivery statuses) to the same
POST endpoint. The structure is always:

  object → entry[] → changes[] → value → messages[] | statuses[]

We model every inbound message type we care about; statuses are a
passthrough dict, acknowledged but unused in Phase 1.

Docs: https://developers.facebook.com/docs/whatsapp/cloud-api/webhooks/payload-examples
"""

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Message-type-specific payloads
# ---------------------------------------------------------------------------


class TextPayload(BaseModel):
    body: str


class MediaPayload(BaseModel):
    """Shared structure for audio, image, video, document, sticker."""

    id: str  # Media ID — use to download via the Media API
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


# ---------------------------------------------------------------------------
# Top-level message object
# ---------------------------------------------------------------------------


class InboundMessage(BaseModel):
    """A single inbound message inside value.messages[]."""

    id: str  # wamid.xxx — use as idempotency / dedup key
    from_: str = Field(alias="from")  # sender wa_id (E.164, no +)
    timestamp: str  # Unix timestamp string
    type: str  # text | audio | image | video | document | location | button | interactive | reaction

    # Type-specific payloads — only one will be present per message
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
        """Convenience: extract text regardless of message type."""
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
        """Convenience: extract media ID for downloadable types."""
        media = self.audio or self.image or self.video or self.document or self.sticker
        return media.id if media else None


# ---------------------------------------------------------------------------
# Delivery status (we acknowledge but ignore in Phase 1)
# ---------------------------------------------------------------------------


class MessageDeliveryStatus(StrEnum):
    """
    Meta's own message delivery status vocabulary — not ours to define, so
    this only names the values Meta currently documents.

    UNKNOWN is a local fallback, never sent by Meta itself: _missing_ maps
    any value we don't recognize to it, so a status Meta adds later gets
    parsed as "unknown" instead of rejecting the whole webhook payload —
    correct given we only acknowledge these in Phase 1, never branch on them.
    """

    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"
    DELETED = "deleted"
    WARNING = "warning"
    UNKNOWN = "unknown"

    @classmethod
    def _missing_(cls, value: object) -> "MessageDeliveryStatus":  # noqa: ARG003 — Enum's hook signature; any unrecognized value maps to UNKNOWN
        return cls.UNKNOWN


class MessageStatus(BaseModel):
    id: str
    status: MessageDeliveryStatus
    timestamp: str
    recipient_id: str
    errors: list[dict[str, Any]] | None = None


# ---------------------------------------------------------------------------
# Webhook envelope
# ---------------------------------------------------------------------------


class WebhookContact(BaseModel):
    """Sender profile info, parallel to messages[]."""

    profile: ContactProfile
    wa_id: str


class WebhookMetadata(BaseModel):
    display_phone_number: str
    phone_number_id: str


class WebhookValue(BaseModel):
    """The core payload inside each change."""

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


# ---------------------------------------------------------------------------
# Webhook endpoint response
# ---------------------------------------------------------------------------


class WebhookAckData(BaseModel):
    """Data payload returned by POST /webhooks/whatsapp."""

    workflows_started: int
