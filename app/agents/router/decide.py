"""
decide_action — pure post-processing of a MessageClassification into a
RoutingDecision. No I/O; the classifier call already happened.
"""

from app.schemas.workflows.conversation import (
    NON_SKILL_DOMAINS,
    MessageClassification,
    NonSkillDomain,
    RoutingAction,
    RoutingDecision,
)


def decide_action(
    classification: MessageClassification,
    *,
    confidence_threshold: float,
    available_domains: list[str] | None = None,
    force_clarify: bool = False,
) -> RoutingDecision:
    """`force_clarify` routes to CLARIFY regardless of confidence — used by the
    self-consistency fallback in route_message() when two classification passes
    disagree."""
    available_domains = available_domains or []
    primary = classification.primary

    if primary is None:
        return RoutingDecision(
            action=RoutingAction.CHITCHAT_REPLY,
            classification=classification,
            available_domains=available_domains,
        )

    if primary.domain == NonSkillDomain.CHITCHAT:
        return RoutingDecision(
            action=RoutingAction.CHITCHAT_REPLY,
            classification=classification,
            primary_domain=primary.domain,
            available_domains=available_domains,
        )

    if primary.domain == NonSkillDomain.OUT_OF_SCOPE:
        return RoutingDecision(
            action=RoutingAction.DEFER_OUT_OF_SCOPE,
            classification=classification,
            primary_domain=primary.domain,
            available_domains=available_domains,
        )

    if force_clarify or primary.confidence < confidence_threshold:
        return RoutingDecision(
            action=RoutingAction.CLARIFY,
            classification=classification,
            primary_domain=primary.domain,  # best-guess, set even though sub-threshold
            available_domains=available_domains,
        )

    secondary_domains = [
        intent.domain
        for intent in classification.intents
        if intent is not primary and intent.domain not in NON_SKILL_DOMAINS
    ]
    if secondary_domains:
        return RoutingDecision(
            action=RoutingAction.DISPATCH_MULTI,
            classification=classification,
            primary_domain=primary.domain,
            secondary_domains=secondary_domains,
            available_domains=available_domains,
        )

    return RoutingDecision(
        action=RoutingAction.DISPATCH,
        classification=classification,
        primary_domain=primary.domain,
        available_domains=available_domains,
    )
