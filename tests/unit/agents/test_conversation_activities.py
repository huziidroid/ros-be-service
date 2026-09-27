"""
Unit tests for app.activities.conversation — @activity.defn-wrapped functions stay
directly callable, so these run without a worker, with the client/router calls mocked.
"""

from unittest.mock import AsyncMock, patch

import pytest
from temporalio.exceptions import ApplicationError

from app.activities.conversation import (
    classify,
    send_clarify_options,
    send_whatsapp_reply,
)
from app.clients.whatsapp import WhatsAppAPIError
from app.schemas.workflows.conversation import (
    ClarifyReplyInput,
    ClassifyInput,
    IntentMatch,
    MessageClassification,
    RoutingAction,
    RoutingDecision,
    SendReplyInput,
)


async def test_classify_delegates_to_route_message() -> None:
    expected = RoutingDecision(
        action=RoutingAction.DISPATCH,
        classification=MessageClassification(
            intents=[IntentMatch(domain="order", confidence=0.9)]
        ),
        primary_domain="order",
    )
    with patch(
        "app.activities.conversation.route_message",
        new=AsyncMock(return_value=expected),
    ) as mocked:
        result = await classify(
            ClassifyInput(text="where is my order", recent_turns=[])
        )

    assert result is expected
    mocked.assert_called_once_with("where is my order", [])


async def test_send_whatsapp_reply_calls_client() -> None:
    with patch(
        "app.activities.conversation.send_text_message", new=AsyncMock(return_value={})
    ) as mocked:
        await send_whatsapp_reply(
            SendReplyInput(phone_number_id="pn1", to="1555", text="hi")
        )

    mocked.assert_called_once_with("pn1", "1555", "hi")


async def test_send_whatsapp_reply_wraps_api_error() -> None:
    with (
        patch(
            "app.activities.conversation.send_text_message",
            new=AsyncMock(side_effect=WhatsAppAPIError(500, {"error": {}})),
        ),
        pytest.raises(ApplicationError),
    ):
        await send_whatsapp_reply(
            SendReplyInput(phone_number_id="pn1", to="1555", text="hi")
        )


async def test_send_clarify_options_builds_list_interactive_with_domain_rows() -> None:
    with patch(
        "app.activities.conversation.send_interactive_message",
        new=AsyncMock(return_value={}),
    ) as mocked:
        await send_clarify_options(
            ClarifyReplyInput(
                phone_number_id="pn1",
                to="1555",
                body="Which one?",
                options=["order", "support", "payment", "catalog"],
            )
        )

    mocked.assert_called_once()
    _, _, interactive = mocked.call_args.args
    assert interactive["type"] == "list"
    assert interactive["body"]["text"] == "Which one?"
    row_ids = [row["id"] for row in interactive["action"]["sections"][0]["rows"]]
    assert row_ids == ["order", "support", "payment", "catalog"]


async def test_send_clarify_options_wraps_api_error() -> None:
    with (
        patch(
            "app.activities.conversation.send_interactive_message",
            new=AsyncMock(side_effect=WhatsAppAPIError(500, {"error": {}})),
        ),
        pytest.raises(ApplicationError),
    ):
        await send_clarify_options(
            ClarifyReplyInput(
                phone_number_id="pn1", to="1555", body="?", options=["order"]
            )
        )
