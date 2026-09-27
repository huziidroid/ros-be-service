"""Support domain — classifiable now, no agent built yet."""

from app.schemas.workflows.conversation import Skill


SKILL = Skill(
    domain="support",
    description=(
        "General help, complaints, delivery/shipping issues not tied to one order, "
        "account questions, and anything the customer frames as a problem to fix."
    ),
    workflow=None,
)
