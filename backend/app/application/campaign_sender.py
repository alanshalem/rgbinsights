"""Background DM sender for a campaign.

Runs one campaign on its own thread, sending through the shared Instagram source
with strong good-behaviour rails: randomized delays, a per-day cap, an active-
hours window (Argentina local time), and an immediate stop the moment Instagram
pushes back or the account/session/IP is in trouble. State lives in the DB so a
campaign survives an app restart (resume_all on startup).

Sending bulk DMs is the highest-risk IG action; these rails reduce — not
eliminate — the ban risk. Its collaborators (campaign store, Instagram source,
activity feed, clock) are injected by the composition root (app.bootstrap).
"""

from __future__ import annotations

import logging
import random
import threading
import time
from collections.abc import Callable
from datetime import UTC, date, datetime, tzinfo

from app.application import campaign as camp
from app.application.ports import CampaignStore, InstagramSource
from app.domain.errors import (
    BudgetExhaustedError,
    ChallengeRequiredError,
    IgBusyError,
    InstagramError,
    IpBlockedError,
    LoginRequiredError,
    RateLimitedError,
    SendBlockedError,
)

logger = logging.getLogger(__name__)

_CHUNK_SECONDS = 3.0
_IDLE_SECONDS = 60  # re-check interval outside active hours / over the daily cap
_BUSY_SECONDS = 30  # another Instagram operation is running: wait, then retry
# Extra wait after our request budget reopens, so sends don't fire right on the
# hour like a cron job.
_BUDGET_JITTER_SECONDS = (60.0, 300.0)

# Instagram pushed back on sending: "blocked" (the UI explains the action-block).
_BLOCK_ERRORS = (SendBlockedError, ChallengeRequiredError)
# The account/session/IP can't send, or Instagram asked us to slow down
# (cooldown): "paused" with the reason. The same target stays pending, so
# resuming retries it — no target is burned and no new login is attempted per
# target. Our own spent request budget (BudgetExhaustedError) is not a pause:
# the sender waits for the window to reopen and continues by itself.
_PAUSE_ERRORS = (LoginRequiredError, IpBlockedError, RateLimitedError)

# activity(kind, status, message): one row in the activity feed.
ActivityFn = Callable[[str, str, str], None]


def _utcnow() -> datetime:
    return datetime.now(UTC)


class CampaignSender:
    def __init__(
        self,
        store: CampaignStore,
        source: Callable[[], InstagramSource],
        tz: tzinfo,
        activity: ActivityFn,
        *,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._store = store
        self._source = source  # resolved per run: the process-wide shared source
        self._tz = tz
        self._activity = activity
        self._clock = clock
        self._threads: dict[int, threading.Thread] = {}
        self._lock = threading.Lock()

    def start(self, campaign_id: int) -> None:
        """Spawn the sender thread for a campaign (no-op if already running)."""
        with self._lock:
            existing = self._threads.get(campaign_id)
            if existing is not None and existing.is_alive():
                return
            thread = threading.Thread(target=self._run, args=(campaign_id,), daemon=True)
            self._threads[campaign_id] = thread
            thread.start()

    def resume_all(self) -> None:
        """On startup, restart any campaign left in the running state."""
        for campaign_id in self._store.running_ids():
            logger.info("resuming campaign %d", campaign_id)
            self.start(campaign_id)

    def _sleep_or_stopped(self, campaign_id: int, seconds: float) -> bool:
        """Sleep in small chunks; return True if the campaign was stopped meanwhile."""
        waited = 0.0
        while waited < seconds:
            if self._store.status(campaign_id) != "running":
                return True
            time.sleep(min(_CHUNK_SECONDS, seconds - waited))
            waited += _CHUNK_SECONDS
        return False

    def _run(self, campaign_id: int) -> None:
        source = self._source()

        while True:
            now = self._clock().astimezone(self._tz)  # hours and days are Argentina local
            campaign = self._store.open_day(campaign_id, now.date())
            if campaign is None or campaign.status != "running":
                return

            day_index = (now.date() - _local_date(campaign.created_at, self._tz)).days
            cap = camp.warmup_cap(campaign.daily_cap, day_index)
            if not _within_active_hours(campaign.hour_start, campaign.hour_end, now) or (
                campaign.sent_today >= cap
            ):
                if self._sleep_or_stopped(campaign_id, _IDLE_SECONDS):
                    return
                continue

            target = self._store.next_pending(campaign_id)
            if target is None:
                self._store.finish(campaign_id)
                self._activity("campaign", "done", f"campaña terminada ({campaign.sent_today} hoy)")
                return

            delay = random.uniform(campaign.delay_min, campaign.delay_max)

            # No transaction is open while we talk to Instagram.
            try:
                source.send_dm(target.user_pk, target.message)
                outcome, error = "sent", None
            except IgBusyError:
                # Another operation holds Instagram; same target, a bit later.
                if self._sleep_or_stopped(campaign_id, _BUSY_SECONDS):
                    return
                continue
            except BudgetExhaustedError as exc:
                # Our hourly/daily budget is spent (nothing wrong with the account):
                # wait for it to reopen — zero Instagram calls meanwhile — then retry
                # the same target.
                wait = max(0.0, (exc.retry_at - self._clock()).total_seconds())
                wait += random.uniform(*_BUDGET_JITTER_SECONDS)
                self._activity("campaign", "error", f"campaña en espera: {exc}")
                logger.info("campaign %d waits %.0f s for the request budget", campaign_id, wait)
                if self._sleep_or_stopped(campaign_id, wait):
                    return
                continue
            except _BLOCK_ERRORS as exc:
                self._halt(campaign_id, "blocked", exc, "campaña frenada")
                return
            except _PAUSE_ERRORS as exc:
                self._halt(campaign_id, "paused", exc, "campaña pausada")
                return
            except InstagramError as exc:
                # This target only (recipient closed DMs, network hiccup): skip it.
                outcome, error = "failed", str(exc)

            self._store.record_send(campaign_id, target.target_id, outcome, error, self._clock())
            # Keep the gap after a failed attempt too: it still reached Instagram.
            if self._sleep_or_stopped(campaign_id, delay):
                return

    def _halt(self, campaign_id: int, status: str, exc: Exception, label: str) -> None:
        """Stop the campaign with a persisted status + reason the UI shows."""
        self._store.halt(campaign_id, status, str(exc))
        self._activity("campaign", "error", f"{label}: {exc}")
        logger.warning("campaign %d %s: %s", campaign_id, status, exc)


def _local_date(when: datetime, tz: tzinfo) -> date:
    """Local calendar date of a stored timestamp (naive values are UTC)."""
    aware = when if when.tzinfo is not None else when.replace(tzinfo=UTC)
    return aware.astimezone(tz).date()


def _within_active_hours(hour_start: int, hour_end: int, now_local: datetime) -> bool:
    return hour_start <= now_local.hour < hour_end
