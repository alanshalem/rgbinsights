"""Shared request cap: a per-run counter that guards against a runaway loop.

The inter-request *delay* is handled by instagrapi itself (`client.delay_range`,
set in session.build_client), so this no longer sleeps — it would just double
the wait. It only counts requests and trips once a top-level operation
(scan / sync / enrich) exceeds its budget. Reset before each operation, so it is
per-operation, not per-process.
"""

from __future__ import annotations

from app.infrastructure.instagram.errors import RateLimitedError


class RequestBudget:
    def __init__(self, max_requests: int) -> None:
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
