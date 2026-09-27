"""
Unit tests for app.agents.router.cascade — mocks classify_message so these run
without touching the LLM. Verifies the *trigger* for the memory-enriched second
pass: ambiguous first pass + non-empty recent_turns, and nothing else.
"""

from unittest.mock import AsyncMock, patch

from app.agents.router.cascade import classify_with_cascade
from app.schemas.workflows.conversation import (
    ConversationTurn,
    IntentMatch,
    MessageClassification,
)


def _classification(domain: str, confidence: float) -> MessageClassification:
    return MessageClassification(
        intents=[IntentMatch(domain=domain, confidence=confidence)]
    )


async def test_confident_first_pass_skips_second_call() -> None:
    confident = _classification("order", 0.95)
    with patch(
        "app.agents.router.cascade.classify_message",
        new=AsyncMock(return_value=confident),
    ) as mocked:
        result = await classify_with_cascade(
            "where is my order",
            [ConversationTurn(role="inbound", text="hi")],
        )

    assert result is confident
    mocked.assert_called_once_with("where is my order")


async def test_ambiguous_first_pass_without_memory_skips_second_call() -> None:
    """No recent_turns means there's nothing for a second pass to add — cascade
    shouldn't spend an extra call on it."""
    ambiguous = _classification("order", 0.3)
    with patch(
        "app.agents.router.cascade.classify_message",
        new=AsyncMock(return_value=ambiguous),
    ) as mocked:
        result = await classify_with_cascade("hmm", [])

    assert result is ambiguous
    mocked.assert_called_once_with("hmm")


async def test_ambiguous_first_pass_with_memory_retries_with_recent_turns() -> None:
    ambiguous = _classification("order", 0.3)
    confident = _classification("support", 0.9)
    turns = [ConversationTurn(role="inbound", text="my delivery is late")]

    with patch(
        "app.agents.router.cascade.classify_message",
        new=AsyncMock(side_effect=[ambiguous, confident]),
    ) as mocked:
        result = await classify_with_cascade("still nothing?", turns)

    assert result is confident
    assert mocked.call_count == 2
    mocked.assert_any_call("still nothing?")
    mocked.assert_any_call("still nothing?", turns)


async def test_no_primary_intent_counts_as_ambiguous() -> None:
    empty = MessageClassification(intents=[])
    confident = _classification("catalog", 0.9)
    turns = [ConversationTurn(role="inbound", text="hey")]

    with patch(
        "app.agents.router.cascade.classify_message",
        new=AsyncMock(side_effect=[empty, confident]),
    ) as mocked:
        result = await classify_with_cascade("???", turns)

    assert result is confident
    assert mocked.call_count == 2
