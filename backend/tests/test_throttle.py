"""S22: RequestBudget, the real per-hour/per-day Instagram request budget (S5)."""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import pytest
from app.domain.errors import BudgetExhaustedError
from app.infrastructure.instagram.throttle import (
    HumanPacer,
    RequestBudget,
    format_local,
    non_negative_int,
)

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


# -- L29 B1: reconfiguring the pacer never stretches the gap between long rests --


def _rest_stretches(delays: list[float]) -> list[int]:
    """Requests between long rests (a delay >= 45 s is a long rest: the base gap
    plus a distraction tops out at 6 + 18 s)."""
    stretches, since = [], 0
    for delay in delays:
        since += 1
        if delay >= 45.0:
            stretches.append(since)
            since = 0
    return [*stretches, since]


@pytest.mark.parametrize(("before", "after"), [(25, 20), (20, 25), (25, 5), (5, 25)])
def test_reconfigured_rests_never_exceed_the_longer_of_both_spacings(
    before: int, after: int
) -> None:
    pacer = HumanPacer(2, 6, rest_every=before, rest_min=45, rest_max=150, rng=random.Random(1))
    delays = [pacer.next_delay() for _ in range(before - 1)]  # one short of a rest
    pacer.configure(2, 6, rest_every=after, rest_min=45, rest_max=150)
    delays += [pacer.next_delay() for _ in range(60)]

    stretches = _rest_stretches(delays)
    assert max(stretches) <= max(before, after)
    assert all(s <= after for s in _rest_stretches(delays[before:])[1:-1])


def test_the_verifier_probe_rests_by_request_25() -> None:
    pacer = HumanPacer(2, 6, rest_every=25, rest_min=45, rest_max=150, rng=random.Random(1))
    delays = [pacer.next_delay() for _ in range(24)]
    pacer.configure(2, 6, rest_every=20, rest_min=45, rest_max=150)
    delays += [pacer.next_delay() for _ in range(30)]

    assert max(_rest_stretches(delays)) <= 25
    assert delays[24] >= 45.0  # 24 since the last rest >= the new 20: rest now


def test_a_steady_spacing_still_rests_every_n_requests() -> None:
    pacer = HumanPacer(2, 6, rest_every=10, rest_min=45, rest_max=150, rng=random.Random(2))
    delays = [pacer.next_delay() for _ in range(35)]
    assert [i + 1 for i, d in enumerate(delays) if d >= 45.0] == [10, 20, 30]


def test_lowered_rest_every_mid_run_never_exceeds_the_larger() -> None:
    for a, b in [(24, 20), (25, 5), (20, 24)]:
        for s in range(60):
            p = HumanPacer(0, 0, rest_every=a, rest_min=1000, rest_max=1000, rng=random.Random(1))
            run = worst = 0
            for i in range(200):
                if i == s:
                    p.configure(0, 0, rest_every=b, rest_min=1000, rest_max=1000)
                run += 1
                if p.next_delay() >= 1000:
                    worst = max(worst, run)
                    run = 0
            assert max(worst, run) <= max(a, b), (a, b, s)
