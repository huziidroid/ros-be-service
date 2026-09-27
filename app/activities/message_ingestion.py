"""
Message ingestion activities — turning a raw inbound message into text the router can
classify.

Dispatches by message_type via a flat lookup table. Only "text" is supported today;
every other type comes back "unsupported" so the workflow can acknowledge plainly
instead of crashing.
"""

from collections.abc import Awaitable, Callable

from temporalio import activity

from app.schemas.webhooks.whatsapp import InboundMessage
from app.schemas.workflows.conversation import ExtractedText


async def _extract_text_message(message: InboundMessage) -> ExtractedText:
    return ExtractedText(text=message.text_body, supported=True)


# Async signature, even though the text branch has no I/O — other message types
# (e.g. audio) will need to fetch/transcode media.
_EXTRACTORS: dict[str, Callable[[InboundMessage], Awaitable[ExtractedText]]] = {
    "text": _extract_text_message,
}


@activity.defn
async def extract_text(message: InboundMessage) -> ExtractedText:
    extractor = _EXTRACTORS.get(message.type)
    if extractor is None:
        return ExtractedText(
            text=None,
            supported=False,
            reason=f"message_type '{message.type}' is not supported yet.",
        )
    return await extractor(message)
