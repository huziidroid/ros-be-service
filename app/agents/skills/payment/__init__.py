"""Payment domain — classifiable now, no agent built yet."""

from app.schemas.workflows.conversation import Skill


SKILL = Skill(
    domain="payment",
    description=(
        "Invoices, payment methods, credit line/balance questions, and disputes "
        "about a charge or a payment that didn't go through."
    ),
    workflow=None,
)
