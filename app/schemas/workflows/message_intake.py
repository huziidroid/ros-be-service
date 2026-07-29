"""
Schemas for MessageIntakeWorkflow and its activities.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas.webhooks.whatsapp import InboundMessage


@dataclass
class MessageIntakeInput:
    """
    Input to MessageIntakeWorkflow — everything known about an inbound message
    at the time the webhook fires.
    """

    phone_number_id: str  # which tenant's number received the message
    tenant_waba_id: str  # which tenant's WABA received the message
    message: InboundMessage  # complete inbound message, as received from Meta


__all__ = ["MessageIntakeInput"]
