"""
route_message — combines classification (I/O) and decision (pure) into one call.
Has no Temporal dependency, so it's directly unit-testable.
"""

from app.agents.router.cascade import classify_with_cascade
from app.agents.router.decide import decide_action
from app.agents.skills import SKILL_REGISTRY
from app.core.settings import settings
from app.schemas.workflows.conversation import (
    NON_SKILL_DOMAINS,
    ConversationTurn,
    RoutingDecision,
)


async def route_message(
    text: str, recent_turns: list[ConversationTurn] | None = None
) -> RoutingDecision:
    recent_turns = recent_turns or []
    classification = await classify_with_cascade(text, recent_turns)
    available_domains = sorted(SKILL_REGISTRY)

    if not settings.routing_use_self_consistency:
        return decide_action(
            classification,
            confidence_threshold=settings.routing_confidence_threshold,
            available_domains=available_domains,
        )

    # Categorical outcomes don't need a second opinion — only a real-domain
    # confidence decision does.
    primary = classification.primary
    if primary is None or primary.domain in NON_SKILL_DOMAINS:
        return decide_action(
            classification,
            confidence_threshold=settings.routing_confidence_threshold,
            available_domains=available_domains,
        )

    second_pass = await classify_with_cascade(text, recent_turns)
    second_domain = second_pass.primary.domain if second_pass.primary else None
    agreed = second_domain == primary.domain

    if agreed:
        # Agreement is the trust signal, not the confidence number — bypass the
        # threshold entirely.
        return decide_action(
            classification,
            confidence_threshold=0.0,
            available_domains=available_domains,
        )
    return decide_action(
        classification,
        confidence_threshold=settings.routing_confidence_threshold,
        available_domains=available_domains,
        force_clarify=True,
    )


__all__ = ["route_message"]
