"""S22: RequestBudget, the real per-hour/per-day Instagram request budget (S5)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from app.domain.errors import BudgetExhaustedError
from app.infrastructure.instagram.throttle import RequestBudget, format_local, non_negative_int

AR = timezone(timedelta(hours=-3))
T = datetime(2026, 11, 24, 13, 20, tzinfo=AR)


def test_counts_every_request_in_both_windows() -> None:
    budget = RequestBudget(per_hour=5, per_day=10)
    for _ in range(3):
        budget.spend(T)
    assert budget.counters() == {
        "hour_key": "2026-11-24T13",
        "hour_count": 3,
        "day_key": "2026-11-24",
        "day_count": 3,
    }


def test_hour_cap_stops_until_the_next_hour_and_counts_nothing() -> None:
    budget = RequestBudget(per_hour=2, per_day=10)
    budget.spend(T)
    budget.spend(T)
    with pytest.raises(BudgetExhaustedError) as info:
        budget.spend(T)
    assert info.value.retry_at == datetime(2026, 11, 24, 14, 0, tzinfo=AR)
    assert str(info.value) == (
        "Se alcanzó el tope de seguridad de 2 pedidos a Instagram por hora. "
        "Se reanuda a las 14:00 del 24/11 (hora AR)."
    )
    assert budget.hour_count == 2 and budget.day_count == 2  # the refused one not counted


def test_new_hour_reopens_but_the_day_cap_holds_until_midnight() -> None:
    budget = RequestBudget(per_hour=2, per_day=3)
    budget.spend(T)
    budget.spend(T)
    later = T + timedelta(hours=1)
    budget.spend(later)  # new hour: hourly count restarts
    assert (budget.hour_count, budget.day_count) == (1, 3)
    with pytest.raises(BudgetExhaustedError) as info:
        budget.spend(later)
    assert info.value.retry_at == datetime(2026, 11, 25, 0, 0, tzinfo=AR)
    assert "por día" in str(info.value)
    budget.spend(datetime(2026, 11, 25, 0, 1, tzinfo=AR))  # the next local day
    assert (budget.hour_count, budget.day_count) == (1, 1)


def test_counters_survive_a_restore() -> None:
    budget = RequestBudget(per_hour=5, per_day=10)
    budget.spend(T)
    restored = RequestBudget(per_hour=5, per_day=10)
    restored.restore(budget.counters())
    assert restored.counters() == budget.counters()


@pytest.mark.parametrize(
    "bad",
    [
        {"hour_key": 1},
        {"hour_count": -1},
        {"day_count": True},
        {"day_count": "3"},
    ],
)
def test_malformed_saved_counters_are_rejected_untouched(bad: dict[str, object]) -> None:
    budget = RequestBudget(per_hour=5, per_day=10)
    budget.spend(T)
    before = budget.counters()
    with pytest.raises(ValueError):
        budget.restore({**before, **bad})
    assert budget.counters() == before


def test_helpers() -> None:
    assert non_negative_int(0) == 0
    with pytest.raises(ValueError):
        non_negative_int(False)
    assert format_local(T) == "13:20 del 24/11"
