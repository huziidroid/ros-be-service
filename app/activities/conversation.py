"""
Conversation activities — Temporal glue around app/agents/router (classification)
and app/clients/whatsapp.py (replies). Kept thin; logic lives in those modules.
"""

from typing import Any

from temporalio import activity
from temporalio.exceptions import ApplicationError

from app.agents.router import route_message
from app.clients.whatsapp import (
    WhatsAppAPIError,
    send_interactive_message,
    send_text_message,
)
from app.schemas.workflows.conversation import (
    ClarifyReplyInput,
    ClassifyInput,
    RoutingDecision,
    SendReplyInput,
)


@activity.defn
async def classify(inp: ClassifyInput) -> RoutingDecision:
    return await route_message(inp.text, inp.recent_turns)


@activity.defn
async def send_whatsapp_reply(inp: SendReplyInput) -> None:
    try:
        await send_text_message(inp.phone_number_id, inp.to, inp.text)
    except WhatsAppAPIError as exc:
        raise ApplicationError(
            f"Failed to send WhatsApp reply to {inp.to}: {exc}",
            type="META_API_ERROR",
        ) from exc


def _build_list_interactive(body: str, options: list[str]) -> dict[str, Any]:
    """WhatsApp list-interactive payload. `options` are domain names; each row's id
    is the domain, so the customer's tap round-trips as an unambiguous domain string."""
    return {
        "type": "list",
        "body": {"text": body},
        "action": {
            "button": "Choose one",
            "sections": [
                {
                    "title": "What's this about?",
                    "rows": [
                        {"id": domain, "title": domain.capitalize()}
                        for domain in options
                    ],
                }
            ],
        },
    }


@activity.defn
async def send_clarify_options(inp: ClarifyReplyInput) -> None:
    interactive = _build_list_interactive(inp.body, inp.options)
    try:
        await send_interactive_message(inp.phone_number_id, inp.to, interactive)
    except WhatsAppAPIError as exc:
        raise ApplicationError(
            f"Failed to send clarify options to {inp.to}: {exc}",
            type="META_API_ERROR",
        ) from exc
