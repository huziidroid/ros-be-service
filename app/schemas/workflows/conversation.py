"""
Schemas for ConversationWorkflow: its signals/activities I/O, and routing types
(classification, decisions, the skill registry).

`IntentMatch.domain` is a plain `str`, not a `Literal` — valid domains come from the
directory-discovered registry in `app/agents/skills/` and are validated there, not here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.core.settings import settings
from app.schemas.webhooks.whatsapp import InboundMessage


# --- Routing: classification ---


class NonSkillDomain(StrEnum):
    """The two classification outcomes that aren't a SKILL_REGISTRY domain."""

    CHITCHAT = "chitchat"
    OUT_OF_SCOPE = "out_of_scope"


class IntentMatch(BaseModel):
    domain: str
    """One of SKILL_REGISTRY's domains, or a NonSkillDomain value."""

    sub_intent: str | None = None
    confidence: float
    entities: dict[str, Any] = Field(default_factory=dict)
    """Untrusted — never interpolate into a prompt or query without validation."""


class MessageClassification(BaseModel):
    intents: list[IntentMatch] = Field(max_length=settings.classify_max_intents)

    @property
    def primary(self) -> IntentMatch | None:
        return max(self.intents, key=lambda i: i.confidence, default=None)


@dataclass
class ConversationTurn:
    role: str  # "inbound" | "outbound"
    text: str | None  # head+tail truncated (first 300 + last 200 chars)
    domain: str | None = None


class RoutingAction(StrEnum):
    DISPATCH = "dispatch"
    DISPATCH_MULTI = "dispatch_multi"
    CLARIFY = "clarify"
    DEFER_OUT_OF_SCOPE = "defer_out_of_scope"
    CHITCHAT_REPLY = "chitchat_reply"


NON_SKILL_DOMAINS = frozenset(NonSkillDomain)


@dataclass
class RoutingDecision:
    action: RoutingAction
    classification: MessageClassification
    primary_domain: str | None = None
    """Best-guess domain — set even when action == CLARIFY."""
    secondary_domains: list[str] = field(default_factory=list)
    available_domains: list[str] = field(default_factory=list)
    """SKILL_REGISTRY's domains at classification time — the options offered on CLARIFY."""


# --- Routing: skill registry ---


@dataclass
class Skill:
    """One entry in the domain registry (`app/agents/skills/`)."""

    domain: str
    description: str
    """Feeds the router's classification prompt."""

    workflow: type | None = None
    """None = classifiable but no agent built yet."""

    confidence_threshold: float = 0.6


# --- ConversationWorkflow: signal + config + state ---


@dataclass
class NewMessageSignal:
    """Payload of the "new_message" signal to ConversationWorkflow."""

    phone_number_id: str  # which tenant's number received the message
    tenant_waba_id: str  # which tenant's WABA received the message
    message: InboundMessage  # complete inbound message, as received from Meta


@dataclass
class ConversationWorkflowConfig:
    """Tunable conversation settings, read once from app settings and passed into the
    workflow as its own input (never read live inside workflow code)."""

    idle_minutes: int
    close_days: int
    memory_turns: int

    @classmethod
    def from_settings(cls) -> ConversationWorkflowConfig:
        return cls(
            idle_minutes=settings.routing_conversation_idle_minutes,
            close_days=settings.routing_conversation_close_days,
            memory_turns=settings.routing_memory_turns,
        )


@dataclass
class ConversationWorkflowState:
    """Runtime state carried forward across continue-as-new."""

    active_domain: str | None = None
    recent_turns: list[ConversationTurn] = field(default_factory=list)
    seen_wamids: list[str] = field(default_factory=list)


# --- Activity I/O ---


@dataclass
class ExtractedText:
    """Result of app/activities/message_ingestion.py::extract_text."""

    text: str | None
    supported: bool
    reason: str | None = None  # set when supported=False — why, for the ack reply


@dataclass
class ClassifyInput:
    """Input to app/activities/conversation.py::classify."""

    text: str
    recent_turns: list[ConversationTurn]


@dataclass
class SendReplyInput:
    """Input to app/activities/conversation.py::send_whatsapp_reply."""

    phone_number_id: str
    to: str  # wa_id, E.164 without '+'
    text: str


@dataclass
class ClarifyReplyInput:
    """Input to app/activities/conversation.py::send_clarify_options."""

    phone_number_id: str
    to: str  # wa_id, E.164 without '+'
    body: str
    options: list[str]  # domain names -> list rows


__all__ = [
    "ClarifyReplyInput",
    "ClassifyInput",
    "ConversationTurn",
    "ConversationWorkflowConfig",
    "ConversationWorkflowState",
    "ExtractedText",
    "IntentMatch",
    "MessageClassification",
    "NewMessageSignal",
    "NON_SKILL_DOMAINS",
    "NonSkillDomain",
    "RoutingAction",
    "RoutingDecision",
    "SendReplyInput",
    "Skill",
]
