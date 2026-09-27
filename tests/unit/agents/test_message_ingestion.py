"""
Unit tests for app.activities.message_ingestion — @activity.defn-wrapped functions
stay directly callable as plain async functions, so these run without a worker.
"""

from app.activities.message_ingestion import extract_text
from app.schemas.webhooks.whatsapp import InboundMessage, TextPayload


def _text_message(body: str) -> InboundMessage:
    return InboundMessage(
        id="wamid.1",
        from_="15551234567",
        timestamp="1700000000",
        type="text",
        text=TextPayload(body=body),
    )


def _audio_message() -> InboundMessage:
    return InboundMessage(
        id="wamid.2",
        from_="15551234567",
        timestamp="1700000000",
        type="audio",
    )


async def test_text_message_is_supported_and_passthrough() -> None:
    result = await extract_text(_text_message("where is my order?"))
    assert result.supported is True
    assert result.text == "where is my order?"
    assert result.reason is None


async def test_audio_message_is_unsupported_today() -> None:
    """Non-text types come back unsupported with a reason, not a crash."""
    result = await extract_text(_audio_message())
    assert result.supported is False
    assert result.text is None
    assert result.reason is not None
    assert "audio" in result.reason
