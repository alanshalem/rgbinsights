from __future__ import annotations

from datetime import UTC, datetime

import pytest
from app.api.routers.admin import reset_all
from app.api.schemas import ResetIn
from app.application.use_cases import ScanPostUseCase, SyncDmsUseCase
from app.infrastructure.instagram.fake_source import FakeInstagramSource
from app.infrastructure.persistence import models
from fastapi import HTTPException
from sqlmodel import Session, func, select

POST_A_URL = "https://instagram.com/p/Cabc123/"


def _seed(session: Session) -> None:
    source = FakeInstagramSource()
    ScanPostUseCase(source, session).execute(POST_A_URL)
    SyncDmsUseCase(source, session).execute()


def _count(session: Session, model: type) -> int:
    return int(session.exec(select(func.count()).select_from(model)).one())


def test_reset_wipes_everything(session: Session) -> None:
    _seed(session)
    assert _count(session, models.User) > 0

    out = reset_all(ResetIn(confirm="BORRAR TODO"), session)

    assert out.deleted["users"] > 0
    for model in (models.User, models.Post, models.Engagement, models.DmThread):
        assert _count(session, model) == 0


def test_reset_requires_exact_phrase(session: Session) -> None:
    _seed(session)
    with pytest.raises(HTTPException) as exc:
        reset_all(ResetIn(confirm="borrar"), session)
    assert exc.value.status_code == 422
    assert _count(session, models.User) > 0  # nothing deleted


def test_reset_blocked_while_campaign_active(session: Session) -> None:
    _seed(session)
    session.add(
        models.Campaign(
            event_id=1,
            status="running",
            templates="[]",
            delay_min=60,
            delay_max=180,
            daily_cap=25,
            hour_start=11,
            hour_end=23,
            created_at=datetime.now(UTC),
        )
    )
    session.commit()
    with pytest.raises(HTTPException) as exc:
        reset_all(ResetIn(confirm="BORRAR TODO"), session)
    assert exc.value.status_code == 409
