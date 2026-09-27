"""
LangChain structured-output classifier — the one LLM call at the heart of routing.

Goes through build_agent() like every other agent, so baseline middleware (PII
redaction) applies. No tools — reads the result off `structured_response`.
"""

from functools import cache
from typing import Any, cast

from langchain_core.messages import HumanMessage
from langchain_core.runnables import Runnable

from app.agents.base.agent import build_agent
from app.agents.skills import SKILL_REGISTRY
from app.core.settings import settings
from app.schemas.workflows.conversation import (
    ConversationTurn,
    MessageClassification,
    NonSkillDomain,
)


def _classifier_instructions() -> str:
    """Static classifier prompt: skill descriptions and output format. Must stay
    identical call to call so it stays cacheable — no message-specific content."""
    skill_lines = "\n".join(
        f"- {domain}: {skill.description}"
        for domain, skill in sorted(SKILL_REGISTRY.items())
    )
    return (
        f"You are the routing classifier for {settings.app_name}. Classify the "
        "customer's message into one or more of the following business domains, or into "
        f"'{NonSkillDomain.CHITCHAT}' (small talk, greetings, thanks — nothing to "
        f"route) or '{NonSkillDomain.OUT_OF_SCOPE}' (unrelated to this business "
        "entirely).\n\n"
        f"Domains:\n{skill_lines}\n\n"
        "Return up to 3 intents, ranked by confidence from 0.0 to 1.0. Most messages "
        "have exactly one intent — only return more than one when the message "
        'genuinely spans domains (e.g. "check my order and your return policy").'
    )


@cache
def _classifier_agent() -> Runnable[Any, Any]:
    """Built once per process — the system prompt is fixed for the process lifetime."""
    return build_agent(
        extra_instructions=_classifier_instructions(),
        response_format=MessageClassification,
        name="router_classifier",
    )


def _memory_context(recent_turns: list[ConversationTurn]) -> str:
    """Dynamic content, appended to the human message rather than the system prompt
    so the cached prefix never changes."""
    turns_with_text = [t for t in recent_turns if t.text]
    if not turns_with_text:
        return ""
    lines = "\n".join(f"{t.role}: {t.text}" for t in turns_with_text)
    return f"Recent conversation:\n{lines}\n\n"


async def classify_message(
    text: str, recent_turns: list[ConversationTurn] | None = None
) -> MessageClassification:
    """One classification call, optionally with recent conversation turns for context."""
    context = _memory_context(recent_turns or [])
    result = await _classifier_agent().ainvoke(
        {"messages": [HumanMessage(content=f"{context}Customer message: {text}")]}
    )
    return cast("MessageClassification", result["structured_response"])
