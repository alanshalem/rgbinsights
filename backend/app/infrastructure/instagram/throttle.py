"""Pacing and request budget for every Instagram HTTP request (S5, S7).

Pure logic, no I/O: the IgGuard (guard.py) owns persistence and calls these
before each request. Time windows use the account's local (Argentina) time.
"""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any

from app.infrastructure.instagram.errors import BudgetExhaustedError

# Now and then a person gets distracted: add a longer pause on top.
_DISTRACTION_CHANCE = 0.1
_DISTRACTION_FACTOR = 3.0  # the extra pause is up to this many times max_delay


class HumanPacer:
    """Jittered, non-uniform gaps between requests, plus a long rest every N.

    The base gap is triangular around the midpoint of [min, max] (mean equals
    the old uniform delay's mean, so it is never faster); the occasional
    distraction and the periodic rest only add time. Every value is bounded.
    """

    def __init__(
        self,
        min_delay: float,
        max_delay: float,
        *,
        rest_every: int,
        rest_min: float,
        rest_max: float,
        rng: random.Random | None = None,
    ) -> None:
        self._min = max(0.0, min_delay)
        self._max = max(self._min, max_delay)
        self._rest_every = rest_every
        self._rest_min = max(0.0, rest_min)
        self._rest_max = max(self._rest_min, rest_max)
        self._rng = rng or random.Random()
        self._count = 0

    def next_delay(self) -> float:
        self._count += 1
        lo, hi = self._min, self._max
        delay = self._rng.triangular(lo, hi, (lo + hi) / 2)
        if self._rng.random() < _DISTRACTION_CHANCE:
            delay += self._rng.uniform(hi, hi * _DISTRACTION_FACTOR)
        if self._rest_every > 0 and self._count % self._rest_every == 0:
            delay += self._rng.uniform(self._rest_min, self._rest_max)
        return delay


@dataclass
class RequestBudget:
    """Per-hour and per-day request counters (local-time windows).

    Serializable so the guard can persist it; counters reset when the window
    key (local hour / local date) changes.
    """

    per_hour: int
    per_day: int
    hour_key: str = ""
    hour_count: int = 0
    day_key: str = ""
    day_count: int = 0

    def spend(self, now_local: datetime) -> None:
        """Count one request, or raise BudgetExhaustedError if a cap is reached."""
        hour_key = now_local.strftime("%Y-%m-%dT%H")
        day_key = now_local.date().isoformat()
        if hour_key != self.hour_key:
            self.hour_key, self.hour_count = hour_key, 0
        if day_key != self.day_key:
            self.day_key, self.day_count = day_key, 0
        if self.day_count >= self.per_day:
            midnight = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
            raise _cap_error(self.per_day, "día", midnight + timedelta(days=1))
        if self.hour_count >= self.per_hour:
            top = now_local.replace(minute=0, second=0, microsecond=0)
            raise _cap_error(self.per_hour, "hora", top + timedelta(hours=1))
        self.hour_count += 1
        self.day_count += 1

    def counters(self) -> dict[str, Any]:
        data = asdict(self)
        del data["per_hour"], data["per_day"]  # caps come from settings, not the file
        return data

    def restore(self, data: dict[str, Any]) -> None:
        """Load saved counters. Malformed data raises ValueError and leaves the
        counters untouched (all fields are validated before any is assigned)."""
        hour_key, day_key = data.get("hour_key", ""), data.get("day_key", "")
        if not isinstance(hour_key, str) or not isinstance(day_key, str):
            raise ValueError("budget window keys must be strings")
        hour_count = non_negative_int(data.get("hour_count", 0))
        day_count = non_negative_int(data.get("day_count", 0))
        self.hour_key, self.hour_count = hour_key, hour_count
        self.day_key, self.day_count = day_key, day_count


def non_negative_int(value: Any) -> int:
    """A saved counter: a real non-negative int (not a bool/str), else ValueError."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"not a counter: {value!r}")
    return value


def format_local(when: datetime) -> str:
    """'13:00 del 24/11' — how every rail tells the user until when it waits."""
    return f"{when:%H:%M} del {when:%d/%m}"


def _cap_error(cap: int, window: str, resume: datetime) -> BudgetExhaustedError:
    return BudgetExhaustedError(
        f"Se alcanzó el tope de seguridad de {cap} pedidos a Instagram por {window}. "
        f"Se reanuda a las {format_local(resume)} (hora AR).",
        retry_at=resume,
    )
