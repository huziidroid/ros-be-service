"""
Tenant onboarding domain helpers — pure functions, no I/O, fully unit-testable.

Covers WABA selection when Embedded Signup returns more than one account.
"""

import logging

from app.schemas.workflows import WABAInfo


logger = logging.getLogger(__name__)


def select_primary_waba(
    waba_accounts: list[WABAInfo],
    preferred_waba_id: str | None = None,
) -> WABAInfo:
    """
    Choose which WABA to onboard when more than one is returned.

    Embedded Signup v4 supports multi-WABA flows (`waba_ids` instead of a
    single `waba_id`). If the caller knows which one the customer picked,
    pass it as `preferred_waba_id` to take priority.

    Falls back to the sole entry when there's one, or the first entry (with
    a logged warning) when several exist and none match — ambiguous, but
    better than a hard failure.

    Raises ValueError if `waba_accounts` is empty.
    """
    if not waba_accounts:
        raise ValueError("select_primary_waba called with an empty list.")

    if preferred_waba_id is not None:
        for waba in waba_accounts:
            if waba.id == preferred_waba_id:
                return waba
        logger.warning(
            "preferred_waba_id_not_found",
            extra={
                "preferred_waba_id": preferred_waba_id,
                "available_ids": [w.id for w in waba_accounts],
            },
        )

    if len(waba_accounts) > 1:
        logger.warning(
            "ambiguous_multi_waba_selection",
            extra={
                "selected_id": waba_accounts[0].id,
                "available_ids": [w.id for w in waba_accounts],
            },
        )

    return waba_accounts[0]
