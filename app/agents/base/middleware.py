"""
Baseline governance middleware, applied to every agent by build_agent().

Only universal, tool-agnostic middleware belongs here. HumanInTheLoopMiddleware isn't
part of the baseline since its interrupt_on policy depends on an agent's own tools;
each agent with tools builds its own via human_in_the_loop() below.
"""

from collections.abc import Sequence

from langchain.agents.middleware import (
    AgentMiddleware,
    HumanInTheLoopMiddleware,
    PIIMiddleware,
)
from langchain.agents.middleware.human_in_the_loop import InterruptOnConfig


# Redact PII before it reaches the model and before tool results/output get logged.
# Detection only — never blocks silently; strategy="redact" keeps the conversation
# flowing with the sensitive value masked out.
BASELINE_MIDDLEWARE: Sequence[AgentMiddleware] = (
    PIIMiddleware(
        "email",
        strategy="redact",
        apply_to_input=True,
        apply_to_output=True,
        apply_to_tool_results=True,
    ),
    PIIMiddleware(
        "credit_card",
        strategy="redact",
        apply_to_input=True,
        apply_to_output=True,
        apply_to_tool_results=True,
    ),
)


def human_in_the_loop(
    interrupt_on: dict[str, bool | InterruptOnConfig],
) -> HumanInTheLoopMiddleware:
    """
    Per-agent HITL middleware. Callers pass a risk classification of their own tools,
    e.g. {"get_order_status": False, "cancel_order": True, "issue_refund": True} —
    read-only tools auto-approved, state-changing tools require approval before running.

    Requires build_agent()'s caller to also pass a checkpointer (AsyncPostgresSaver in
    production) — an interrupt must survive a pause, which needs durable state.
    """
    return HumanInTheLoopMiddleware(interrupt_on=interrupt_on)
