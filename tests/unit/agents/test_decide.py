"""
Unit tests for app.agents.router.decide — pure post-processing, no I/O, so these run
without touching the LLM.
"""

from app.agents.router.decide import decide_action
from app.schemas.workflows.conversation import (
    IntentMatch,
    MessageClassification,
    NonSkillDomain,
    RoutingAction,
)


def _classification(*intents: IntentMatch) -> MessageClassification:
    return MessageClassification(intents=list(intents))


def test_high_confidence_single_domain_dispatches() -> None:
    decision = decide_action(
        _classification(IntentMatch(domain="order", confidence=0.92)),
        confidence_threshold=0.6,
    )
    assert decision.action == RoutingAction.DISPATCH
    assert decision.primary_domain == "order"
    assert decision.secondary_domains == []


def test_low_confidence_clarifies_and_still_sets_primary_domain() -> None:
    """primary_domain must be populated even on CLARIFY, or the clarify-then-answer
    fast path silently does nothing."""
    decision = decide_action(
        _classification(IntentMatch(domain="payment", confidence=0.3)),
        confidence_threshold=0.6,
    )
    assert decision.action == RoutingAction.CLARIFY
    assert decision.primary_domain == "payment"


def test_multi_intent_dispatches_multi_with_secondary_domains() -> None:
    decision = decide_action(
        _classification(
            IntentMatch(domain="order", confidence=0.9),
            IntentMatch(domain="support", confidence=0.7),
        ),
        confidence_threshold=0.6,
    )
    assert decision.action == RoutingAction.DISPATCH_MULTI
    assert decision.primary_domain == "order"
    assert decision.secondary_domains == ["support"]


def test_chitchat_domain_replies_as_chitchat() -> None:
    decision = decide_action(
        _classification(IntentMatch(domain=NonSkillDomain.CHITCHAT, confidence=0.95)),
        confidence_threshold=0.6,
    )
    assert decision.action == RoutingAction.CHITCHAT_REPLY
    assert decision.primary_domain == NonSkillDomain.CHITCHAT


def test_out_of_scope_domain_defers() -> None:
    decision = decide_action(
        _classification(
            IntentMatch(domain=NonSkillDomain.OUT_OF_SCOPE, confidence=0.95)
        ),
        confidence_threshold=0.6,
    )
    assert decision.action == RoutingAction.DEFER_OUT_OF_SCOPE
    assert decision.primary_domain == NonSkillDomain.OUT_OF_SCOPE


def test_no_intents_falls_back_to_chitchat_with_no_primary_domain() -> None:
    decision = decide_action(_classification(), confidence_threshold=0.6)
    assert decision.action == RoutingAction.CHITCHAT_REPLY
    assert decision.primary_domain is None


def test_secondary_domains_exclude_non_skill_outcomes() -> None:
    """NonSkillDomain values should never show up as a secondary domain even if the
    classifier (incorrectly) returns one alongside a real domain."""
    decision = decide_action(
        _classification(
            IntentMatch(domain="order", confidence=0.9),
            IntentMatch(domain=NonSkillDomain.CHITCHAT, confidence=0.5),
        ),
        confidence_threshold=0.6,
    )
    assert decision.action == RoutingAction.DISPATCH
    assert decision.secondary_domains == []
