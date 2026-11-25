"""SqlCampaignStore: the CampaignStore port for the background DM sender."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime

from sqlmodel import Session, col, select

from app.application.ports import CampaignDay, PendingSend
from app.infrastructure.persistence import models


class SqlCampaignStore:
    """Each call opens (and closes) its own session: the sender never holds a
    transaction while it talks to Instagram or sleeps."""

    def __init__(self, new_session: Callable[[], Session]) -> None:
        self._new_session = new_session

    def running_ids(self) -> list[int]:
        with self._new_session() as session:
            rows = session.exec(
                select(models.Campaign.id).where(models.Campaign.status == "running")
            ).all()
        return [cid for cid in rows if cid is not None]

    def status(self, campaign_id: int) -> str:
        with self._new_session() as session:
            row = session.get(models.Campaign, campaign_id)
            return row.status if row is not None else "done"

    def open_day(self, campaign_id: int, today: date) -> CampaignDay | None:
        with self._new_session() as session:
            row = session.get(models.Campaign, campaign_id)
            if row is None:
                return None
            if row.status == "running" and row.sent_today_date != today.isoformat():
                # A new local day: the daily cap counts from zero again. Saved at
                # once, so every send of the day counts against it.
                row.sent_today = 0
                row.sent_today_date = today.isoformat()
                session.add(row)
                session.commit()
                session.refresh(row)
            return CampaignDay(
                status=row.status,
                created_at=row.created_at,
                daily_cap=row.daily_cap,
                sent_today=row.sent_today,
                hour_start=row.hour_start,
                hour_end=row.hour_end,
                delay_min=row.delay_min,
                delay_max=row.delay_max,
            )

    def next_pending(self, campaign_id: int) -> PendingSend | None:
        with self._new_session() as session:
            target = session.exec(
                select(models.CampaignTarget)
                .where(
                    models.CampaignTarget.campaign_id == campaign_id,
                    models.CampaignTarget.status == "pending",
                )
                .order_by(col(models.CampaignTarget.id))
            ).first()
            if target is None:
                return None
            return PendingSend(
                target_id=target.id, user_pk=target.user_pk, message=target.message or ""
            )

    def finish(self, campaign_id: int) -> None:
        self._set_status(campaign_id, "done", None)

    def halt(self, campaign_id: int, status: str, error: str) -> None:
        self._set_status(campaign_id, status, error)

    def _set_status(self, campaign_id: int, status: str, error: str | None) -> None:
        with self._new_session() as session:
            row = session.get(models.Campaign, campaign_id)
            if row is None:
                return
            row.status = status
            if error is not None:
                row.error = error
            session.add(row)
            session.commit()

    def record_send(
        self,
        campaign_id: int,
        target_id: int | None,
        outcome: str,
        error: str | None,
        at: datetime,
    ) -> None:
        with self._new_session() as session:
            campaign = session.get(models.Campaign, campaign_id)
            target = (
                session.get(models.CampaignTarget, target_id) if target_id is not None else None
            )
            if target is not None:
                target.status = outcome
                target.error = error
                target.sent_at = at if outcome == "sent" else None
                session.add(target)
            if campaign is not None and outcome == "sent":
                campaign.sent_today += 1
                campaign.last_sent_at = at
                session.add(campaign)
            session.commit()
