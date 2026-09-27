"""Order domain — classifiable now; a real agent (tools, AgentState) lives here once
one is built."""

from app.schemas.workflows.conversation import Skill


SKILL = Skill(
    domain="order",
    description=(
        "Order status, order history, changes to an existing order, cancellations, "
        "and returns/refunds for a specific order."
    ),
    workflow=None,
)
