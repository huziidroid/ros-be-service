"""
Golden set for the router — labeled example messages used to measure classification
quality (ECE, accuracy) before any confidence threshold is trusted.

Small and hand-labeled; grow this from real traffic edge cases as they surface.
"""

from dataclasses import dataclass

from app.agents.skills import is_known_domain
from app.schemas.workflows.conversation import NonSkillDomain


@dataclass(frozen=True)
class GoldenCase:
    text: str
    expected_domain: str
    """One of SKILL_REGISTRY's domains, or a NonSkillDomain value. expected_domain
    isn't an enum — SKILL_REGISTRY's domains are dynamic — so it's validated against
    the live registry below instead, to catch a typo here rather than a golden case
    that silently always "fails"."""


GOLDEN_SET: tuple[GoldenCase, ...] = (
    # --- order ---
    GoldenCase("Where is my order #4521?", "order"),
    GoldenCase("I want to cancel my last order", "order"),
    GoldenCase("Can I return the items I received yesterday?", "order"),
    # --- support ---
    GoldenCase("My delivery never arrived and no one is responding", "support"),
    GoldenCase("I have a complaint about the driver's behavior", "support"),
    # --- payment ---
    GoldenCase("Can you send me last month's invoice?", "payment"),
    GoldenCase("My payment was deducted twice, please check", "payment"),
    GoldenCase("What's my current credit balance?", "payment"),
    # --- catalog ---
    GoldenCase("Do you have 5kg rice bags in stock?", "catalog"),
    GoldenCase("What's the price of your cooking oil?", "catalog"),
    # --- chitchat ---
    GoldenCase("Hi there!", NonSkillDomain.CHITCHAT),
    GoldenCase("Thank you so much, appreciate it", NonSkillDomain.CHITCHAT),
    # --- out_of_scope ---
    GoldenCase("What's the weather like today?", NonSkillDomain.OUT_OF_SCOPE),
    GoldenCase("Can you help me book a flight?", NonSkillDomain.OUT_OF_SCOPE),
)

for _case in GOLDEN_SET:
    if not is_known_domain(_case.expected_domain):
        raise RuntimeError(
            f"GoldenCase {_case.text!r} has unknown expected_domain "
            f"'{_case.expected_domain}' — not in SKILL_REGISTRY or NonSkillDomain."
        )
del _case


__all__ = ["GOLDEN_SET", "GoldenCase"]
