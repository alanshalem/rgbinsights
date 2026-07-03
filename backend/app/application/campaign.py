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


@dataclass(frozen=True, slots=True)
class Estimate:
    per_day: int
    days: int
    avg_delay_seconds: float


def estimate(count: int, params: SendParams) -> Estimate:
    """How long to send `count` DMs under these params."""
    avg = (params.delay_min + params.delay_max) / 2
    window_hours = (params.hour_end - params.hour_start) % 24 or 24
    max_by_time = int(window_hours * 3600 / avg) if avg > 0 else count
    per_day = max(1, min(params.daily_cap, max_by_time))
    days = math.ceil(count / per_day) if count > 0 else 0
    return Estimate(per_day=per_day, days=days, avg_delay_seconds=avg)


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
