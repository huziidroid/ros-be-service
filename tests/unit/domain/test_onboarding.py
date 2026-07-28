"""
Unit tests for app.domain.onboarding — pure functions, no mocks.
"""

import pytest

from app.domain.onboarding import select_primary_waba
from app.schemas.workflows import WABAInfo


def _waba(id_: str, currency: str = "PKR") -> WABAInfo:
    return WABAInfo(id=id_, name=f"Business {id_}", currency=currency)


class TestSelectPrimaryWaba:
    def test_raises_on_empty_list(self) -> None:
        with pytest.raises(ValueError):
            select_primary_waba([])

    def test_single_waba_is_returned(self) -> None:
        waba = _waba("waba-1")
        assert select_primary_waba([waba]) is waba

    def test_preferred_waba_id_wins_when_present(self) -> None:
        first, second = _waba("waba-1"), _waba("waba-2")
        result = select_primary_waba([first, second], preferred_waba_id="waba-2")
        assert result is second

    def test_falls_back_to_first_when_preferred_not_found(self) -> None:
        first, second = _waba("waba-1"), _waba("waba-2")
        result = select_primary_waba(
            [first, second], preferred_waba_id="does-not-exist"
        )
        assert result is first

    def test_falls_back_to_first_when_ambiguous(self) -> None:
        first, second = _waba("waba-1"), _waba("waba-2")
        assert select_primary_waba([first, second]) is first
