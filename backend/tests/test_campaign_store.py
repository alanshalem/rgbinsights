"""Daily-cap rollover in the campaign store (T6a fix): a new day resets a running
campaign's counter and persists it; a paused campaign is never reset."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from app.infrastructure.persistence import db, models
from app.infrastructure.persistence.campaigns import SqlCampaignStore
from sqlmodel import Session


def _store(tmp_path: Path, status: str) -> tuple[SqlCampaignStore, int]:
    eng = db.build_engine(f"sqlite:///{tmp_path / 'c.db'}")
    db.create_db_and_tables(eng)
    now = datetime.now(UTC)
    with Session(eng) as s:
        ev = models.Event(name="e", promo_start=now, event_date=now, created_at=now)
        s.add(ev)
        s.commit()
        s.refresh(ev)
        assert ev.id is not None
        c = models.Campaign(
            event_id=ev.id,
            status=status,
            templates="[]",
            daily_cap=2,
            delay_min=0,
            delay_max=0,
            hour_start=0,
            hour_end=24,
            sent_today=7,
            sent_today_date="2000-01-01",
            created_at=now,
        )
        s.add(c)
        s.commit()
        s.refresh(c)
        assert c.id is not None
        return SqlCampaignStore(lambda: Session(eng)), c.id


def test_new_day_resets_a_running_campaign_and_persists(tmp_path: Path) -> None:
    store, cid = _store(tmp_path, "running")
    first = store.open_day(cid, date(2026, 1, 2))
    again = store.open_day(cid, date(2026, 1, 2))  # same day: the reset was saved
    assert first is not None and first.sent_today == 0
    assert again is not None and again.sent_today == 0


def test_new_day_never_resets_a_paused_campaign(tmp_path: Path) -> None:
    store, cid = _store(tmp_path, "paused")
    day = store.open_day(cid, date(2026, 1, 2))
    assert day is not None
    assert (day.status, day.sent_today) == ("paused", 7)
