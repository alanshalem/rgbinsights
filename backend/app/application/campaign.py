"""Pure helpers for DM campaigns: safety presets, ETA, message rendering.

No I/O — unit-tested. The sending engine (campaign_sender.py) uses these.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SendParams:
    """Rate-limiting / good-behaviour knobs for a campaign."""

    delay_min: int  # seconds between sends (lower bound)
    delay_max: int  # seconds between sends (upper bound)
    daily_cap: int  # max sends per calendar day
    hour_start: int  # active window start hour [0..24)
    hour_end: int  # active window end hour (exclusive, 1..24)


# Selectable presets, ordered from safest. "custom" lets the UI tune each knob.
PRESETS: dict[str, SendParams] = {
    "max": SendParams(delay_min=60, delay_max=180, daily_cap=25, hour_start=11, hour_end=23),
    "media": SendParams(delay_min=45, delay_max=120, daily_cap=40, hour_start=10, hour_end=24),
}

# Safety ceiling for the auto/optimal mode: never blast more than this per day,
# even if that means the run spills past the target window. Cold-ish bulk DMs
# above ~45/day sharply raise the action-block risk.
_OPTIMAL_MAX_CAP = 45
_OPTIMAL_HOURS = (10, 23)  # 13h daytime window (AR-friendly)


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))


def optimal_params(count: int, target_days: float = 2.5) -> SendParams:
    """Compute the 'sweet spot' rate for `count` DMs: finish in ~2-3 days as safely
    as possible.

    Strategy: pick the SMALLEST daily cap that still drains the list within the
    target window (bounded by a hard safety ceiling), then stretch the delays so
    those sends spread across the whole active window. Fewer-per-day + long,
    randomized gaps = the least bursty pattern that still meets the deadline —
    the safest point on the speed/ban-risk curve. If the list is too big to
    finish safely in the window, the cap stays at the ceiling and it simply takes
    longer (the ETA shows the real number of days).
    """
    count = max(count, 1)
    hour_start, hour_end = _OPTIMAL_HOURS
    window_seconds = (hour_end - hour_start) * 3600
    needed_cap = math.ceil(count / max(target_days, 0.5))
    daily_cap = _clamp(needed_cap, 1, _OPTIMAL_MAX_CAP)
    avg_gap = window_seconds / daily_cap  # spread the day's sends evenly
    delay_min = _clamp(round(avg_gap * 0.6), 60, 600)
    delay_max = _clamp(round(avg_gap * 1.4), delay_min + 60, 1200)
    return SendParams(
        delay_min=delay_min,
        delay_max=delay_max,
        daily_cap=daily_cap,
        hour_start=hour_start,
        hour_end=hour_end,
    )


@dataclass(frozen=True, slots=True)
class Estimate:
    per_day: int  # messages actually sent on a full day
    days: int  # calendar days to drain the whole list
    avg_delay_seconds: float  # mean gap between two sends
    window_hours: int  # length of the daily active window
    minutes_per_day: float  # minutes of actual sending activity per full day


def estimate(count: int, params: SendParams) -> Estimate:
    """How long to send `count` DMs under these params."""
    avg = (params.delay_min + params.delay_max) / 2
    window_hours = (params.hour_end - params.hour_start) % 24 or 24
    max_by_time = int(window_hours * 3600 / avg) if avg > 0 else count
    per_day = max(1, min(params.daily_cap, max_by_time))
    days = math.ceil(count / per_day) if count > 0 else 0
    return Estimate(
        per_day=per_day,
        days=days,
        avg_delay_seconds=avg,
        window_hours=window_hours,
        minutes_per_day=round(per_day * avg / 60, 1),
    )


def _first_name(full_name: str, username: str) -> str:
    name = full_name.strip()
    return name.split()[0] if name else username


def render_message(templates: list[str], username: str, full_name: str, key: str) -> str:
    """Pick one variant (deterministic per `key`, varied across users) and fill it.

    Rotating variants lowers the "identical bulk message" spam signal. Supported
    placeholders: {nombre} (first name, or username), {usuario}/{username}.
    """
    variants = [t for t in (s.strip() for s in templates) if t]
    if not variants:
        return ""
    idx = int(hashlib.sha1(key.encode()).hexdigest(), 16) % len(variants)
    first = _first_name(full_name, username)
    return (
        variants[idx]
        .replace("{nombre}", first)
        .replace("{usuario}", username)
        .replace("{username}", username)
    )
