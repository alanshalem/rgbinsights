"""Background DM sender for a campaign.

Runs one campaign on its own thread, sending through the shared browser source
with strong good-behaviour rails: randomized delays, a per-day cap, an active-
hours window, and an immediate stop the moment Instagram pushes back. State
lives in the DB so a campaign survives an app restart (resume_all on startup).

Sending bulk DMs is the highest-risk IG action; these rails reduce — not
eliminate — the ban risk.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from datetime import UTC, datetime

from sqlmodel import Session, select

from app.infrastructure.config.settings import get_settings
from app.infrastructure.instagram.errors import (
    ChallengeRequiredError,
    InstagramError,
    SendBlockedError,
)
from app.infrastructure.instagram.shared import get_shared_source
from app.infrastructure.persistence import models
from app.infrastructure.persistence.db import engine

logger = logging.getLogger(__name__)

_threads: dict[int, threading.Thread] = {}
_lock = threading.Lock()
_CHUNK_SECONDS = 3.0


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
    source = get_shared_source(settings.resolved_source())

    while True:
        with Session(engine) as session:
            campaign = session.get(models.Campaign, campaign_id)
            if campaign is None or campaign.status != "running":
                return

            _reset_daily_counter(campaign)

            now = datetime.now(UTC)
            if not _within_active_hours(campaign, now) or campaign.sent_today >= campaign.daily_cap:
                session.add(campaign)
                session.commit()
                if _sleep_or_stopped(campaign_id, 60):
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
                return

            delay = random.uniform(campaign.delay_min, campaign.delay_max)
            message = target.message or ""
            user_pk = target.user_pk

        # Send outside the session so we don't hold a transaction over the network.
        try:
            source.send_dm(user_pk, message)
            outcome, error = "sent", None
        except (SendBlockedError, ChallengeRequiredError) as exc:
            _mark_blocked(campaign_id, str(exc))
            logger.warning("campaign %d blocked: %s", campaign_id, exc)
            return
        except InstagramError as exc:
            outcome, error = "failed", str(exc)

        _record_send(campaign_id, target.id, outcome, error)
        if outcome == "sent" and _sleep_or_stopped(campaign_id, delay):
            return


def _reset_daily_counter(campaign: models.Campaign) -> None:
    today = datetime.now(UTC).date().isoformat()
    if campaign.sent_today_date != today:
        campaign.sent_today = 0
        campaign.sent_today_date = today


def _within_active_hours(campaign: models.Campaign, now: datetime) -> bool:
    return campaign.hour_start <= now.hour < campaign.hour_end


def _mark_blocked(campaign_id: int, error: str) -> None:
    with Session(engine) as session:
        campaign = session.get(models.Campaign, campaign_id)
        if campaign is not None:
            campaign.status = "blocked"
            campaign.error = error
            session.add(campaign)
            session.commit()


def _record_send(campaign_id: int, target_id: int | None, outcome: str, error: str | None) -> None:
    now = datetime.now(UTC)
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
