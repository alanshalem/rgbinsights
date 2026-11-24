"""Background DM sender for a campaign.

Runs one campaign on its own thread, sending through the shared Instagram source
with strong good-behaviour rails: randomized delays, a per-day cap, an active-
hours window (Argentina local time), and an immediate stop the moment Instagram
pushes back or the account/session/IP is in trouble. State lives in the DB so a
campaign survives an app restart (resume_all on startup).

Sending bulk DMs is the highest-risk IG action; these rails reduce — not
eliminate — the ban risk.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from datetime import UTC, date, datetime, tzinfo

from sqlmodel import Session, select

from app.application import campaign as camp
from app.application import tasks
from app.infrastructure.config.settings import get_settings
from app.infrastructure.instagram.errors import (
    ChallengeRequiredError,
    IgBusyError,
    InstagramError,
    IpBlockedError,
    LoginRequiredError,
    RateLimitedError,
    SendBlockedError,
)
from app.infrastructure.instagram.shared import get_shared_source
from app.infrastructure.persistence import models
from app.infrastructure.persistence.db import engine

logger = logging.getLogger(__name__)

_threads: dict[int, threading.Thread] = {}
_lock = threading.Lock()
_CHUNK_SECONDS = 3.0
_IDLE_SECONDS = 60  # re-check interval outside active hours / over the daily cap
_BUSY_SECONDS = 30  # another Instagram operation is running: wait, then retry

# Instagram pushed back on sending: "blocked" (the UI explains the action-block).
_BLOCK_ERRORS = (SendBlockedError, ChallengeRequiredError)
# The account/session/IP or a safety rail can't send right now: "paused" with the
# reason. The same target stays pending, so resuming retries it — no target is
# burned and no new login is attempted per target.
_PAUSE_ERRORS = (LoginRequiredError, IpBlockedError, RateLimitedError)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def start(campaign_id: int) -> None:
    """Spawn the sender thread for a campaign (no-op if already running)."""
    with _lock:
        existing = _threads.get(campaign_id)
        if existing is not None and existing.is_alive():
            return
        thread = threading.Thread(target=_run, args=(campaign_id,), daemon=True)
        _threads[campaign_id] = thread
        thread.start()


def resume_all() -> None:
    """On startup, restart any campaign left in the running state."""
    with Session(engine) as session:
        rows = session.exec(
            select(models.Campaign).where(models.Campaign.status == "running")
        ).all()
    for campaign in rows:
        if campaign.id is not None:
            logger.info("resuming campaign %d", campaign.id)
            start(campaign.id)


def _status(campaign_id: int) -> str:
    with Session(engine) as session:
        row = session.get(models.Campaign, campaign_id)
        return row.status if row is not None else "done"


def _sleep_or_stopped(campaign_id: int, seconds: float) -> bool:
    """Sleep in small chunks; return True if the campaign was stopped meanwhile."""
    waited = 0.0
    while waited < seconds:
        if _status(campaign_id) != "running":
            return True
        time.sleep(min(_CHUNK_SECONDS, seconds - waited))
        waited += _CHUNK_SECONDS
    return False


def _run(campaign_id: int) -> None:
    settings = get_settings()
    tz = settings.local_tz()
    source = get_shared_source(settings.resolved_source())

    while True:
        with Session(engine) as session:
            campaign = session.get(models.Campaign, campaign_id)
            if campaign is None or campaign.status != "running":
                return

            now = _utcnow().astimezone(tz)  # hours and days are Argentina local
            _reset_daily_counter(campaign, now.date())
            day_index = (now.date() - _local_date(campaign.created_at, tz)).days
            cap = camp.warmup_cap(campaign.daily_cap, day_index)
            if not _within_active_hours(campaign, now) or campaign.sent_today >= cap:
                session.add(campaign)
                session.commit()
                if _sleep_or_stopped(campaign_id, _IDLE_SECONDS):
                    return
                continue

            target = session.exec(
                select(models.CampaignTarget)
                .where(
                    models.CampaignTarget.campaign_id == campaign_id,
                    models.CampaignTarget.status == "pending",
                )
                .order_by(models.CampaignTarget.id)  # type: ignore[arg-type]
            ).first()
            if target is None:
                campaign.status = "done"
                session.add(campaign)
                session.commit()
                tasks.log_activity(
                    "campaign", "done", f"campaña terminada ({campaign.sent_today} hoy)"
                )
                return

            delay = random.uniform(campaign.delay_min, campaign.delay_max)
            message = target.message or ""
            user_pk = target.user_pk

        # Send outside the session so we don't hold a transaction over the network.
        try:
            source.send_dm(user_pk, message)
            outcome, error = "sent", None
        except IgBusyError:
            # Another operation holds Instagram; same target, a bit later.
            if _sleep_or_stopped(campaign_id, _BUSY_SECONDS):
                return
            continue
        except _BLOCK_ERRORS as exc:
            _halt(campaign_id, "blocked", exc, "campaña frenada")
            return
        except _PAUSE_ERRORS as exc:
            _halt(campaign_id, "paused", exc, "campaña pausada")
            return
        except InstagramError as exc:
            # This target only (recipient closed DMs, network hiccup): skip it.
            outcome, error = "failed", str(exc)

        _record_send(campaign_id, target.id, outcome, error)
        # Keep the gap after a failed attempt too: it still reached Instagram.
        if _sleep_or_stopped(campaign_id, delay):
            return


def _local_date(when: datetime, tz: tzinfo) -> date:
    """Local calendar date of a stored timestamp (naive values are UTC)."""
    aware = when if when.tzinfo is not None else when.replace(tzinfo=UTC)
    return aware.astimezone(tz).date()


def _reset_daily_counter(campaign: models.Campaign, today: date) -> None:
    if campaign.sent_today_date != today.isoformat():
        campaign.sent_today = 0
        campaign.sent_today_date = today.isoformat()


def _within_active_hours(campaign: models.Campaign, now_local: datetime) -> bool:
    return campaign.hour_start <= now_local.hour < campaign.hour_end


def _halt(campaign_id: int, status: str, exc: Exception, label: str) -> None:
    """Stop the campaign with a persisted status + reason the UI shows."""
    with Session(engine) as session:
        campaign = session.get(models.Campaign, campaign_id)
        if campaign is not None:
            campaign.status = status
            campaign.error = str(exc)
            session.add(campaign)
            session.commit()
    tasks.log_activity("campaign", "error", f"{label}: {exc}")
    logger.warning("campaign %d %s: %s", campaign_id, status, exc)


def _record_send(campaign_id: int, target_id: int | None, outcome: str, error: str | None) -> None:
    now = _utcnow()
    with Session(engine) as session:
        campaign = session.get(models.Campaign, campaign_id)
        target = session.get(models.CampaignTarget, target_id) if target_id is not None else None
        if target is not None:
            target.status = outcome
            target.error = error
            target.sent_at = now if outcome == "sent" else None
            session.add(target)
        if campaign is not None and outcome == "sent":
            campaign.sent_today += 1
            campaign.last_sent_at = now
            session.add(campaign)
        session.commit()
