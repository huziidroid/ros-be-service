"""Catalog domain — classifiable now, no agent built yet."""

from app.schemas.workflows.conversation import Skill


SKILL = Skill(
    domain="catalog",
    description=(
        "Product availability, pricing, specifications, and browsing what a "
        "distributor sells — questions about products in general, not one open order."
    ),
    workflow=None,
)
