"""
classify_with_cascade — a cheap first pass with no memory, then a memory-enriched
retry only when the first pass is ambiguous and there's history to add.
"""

from app.agents.router.classifier import classify_message
from app.core.settings import settings
from app.schemas.workflows.conversation import ConversationTurn, MessageClassification


def _is_ambiguous(classification: MessageClassification) -> bool:
    primary = classification.primary
    return primary is None or primary.confidence < settings.routing_confidence_threshold


async def classify_with_cascade(
    text: str, recent_turns: list[ConversationTurn]
) -> MessageClassification:
    first_pass = await classify_message(text)
    if not _is_ambiguous(first_pass) or not recent_turns:
        return first_pass
    return await classify_message(text, recent_turns)
