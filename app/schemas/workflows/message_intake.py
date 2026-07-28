"""
Schemas for MessageIntakeWorkflow and its activities.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MessageIntakeInput:
    """
    Input to MessageIntakeWorkflow — everything known about an inbound message
    at the time the webhook fires.
    """

    wamid: str  # WhatsApp message ID — used as workflow ID for dedup
    wa_id: str  # sender's WhatsApp number (E.164, no +)
    message_type: str  # text | audio | image | video | document | ...
    phone_number_id: str  # which tenant's number received the message
    text_body: str | None = None
    media_id: str | None = None
    timestamp: str | None = None
    tenant_waba_id: str = ""  # resolved before workflow start; never None


__all__ = ["MessageIntakeInput"]
