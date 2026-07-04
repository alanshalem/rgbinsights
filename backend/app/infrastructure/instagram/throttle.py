"""Shared request throttle: randomized delay + a per-run cap.

The cap guards against a runaway loop; it is reset before each top-level
operation (scan / sync / enrich), so it is per-operation, not per-process.
"""

from __future__ import annotations

import random
import time

from app.infrastructure.instagram.errors import RateLimitedError


class RequestBudget:
    def __init__(self, min_delay: float, max_delay: float, max_requests: int) -> None:
        self._min_delay = min_delay
        self._max_delay = max_delay
        self._max_requests = max_requests
        self._count = 0

    def reset(self) -> None:
        self._count = 0

    def spend(self) -> None:
        self._count += 1
        if self._count > self._max_requests:
            raise RateLimitedError(
                f"request cap reached ({self._max_requests}); stopping to stay safe"
            )
        # Jitter avoids a robotic fixed cadence.
        time.sleep(random.uniform(self._min_delay, self._max_delay))
