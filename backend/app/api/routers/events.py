from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.api.deps import raise_for_err, session_dep, source_dep
from app.api.schemas import EventCreate, EventOut, EventUpdate, ScanBatchResultOut
from app.application.use_cases import RescanEventUseCase
from app.domain.result import Err
from app.infrastructure.config.settings import Settings, get_settings
from app.infrastructure.instagram.base import InstagramSource
from app.infrastructure.persistence import models
from app.infrastructure.persistence.repositories import EventRepository

router = APIRouter(prefix="/events", tags=["events"])


def _to_out(event: models.Event, posts_count: int) -> EventOut:
    assert event.id is not None
    return EventOut(
        id=event.id,
        name=event.name,
        promo_start=event.promo_start,
        event_date=event.event_date,
        notes=event.notes,
        posts_count=posts_count,
    )


@router.post("", response_model=EventOut)
def create_event(body: EventCreate, session: Session = Depends(session_dep)) -> EventOut:
    event = EventRepository(session).create(
        models.Event(
            name=body.name,
            promo_start=body.promo_start,
            event_date=body.event_date,
            notes=body.notes,
            created_at=datetime.now(UTC),
        )
    )
    return _to_out(event, posts_count=0)


@router.get("", response_model=list[EventOut])
def list_events(session: Session = Depends(session_dep)) -> list[EventOut]:
    repo = EventRepository(session)
    counts = repo.post_counts()
    return [_to_out(e, counts.get(e.id or -1, 0)) for e in repo.list_all()]


@router.patch("/{event_id}", response_model=EventOut)
def update_event(
    event_id: int, body: EventUpdate, session: Session = Depends(session_dep)
) -> EventOut:
    repo = EventRepository(session)
    event = repo.get(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "fiesta"})
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(event, field, value)
    session.add(event)
    session.commit()
    session.refresh(event)
    return _to_out(event, repo.post_counts().get(event_id, 0))


@router.post("/{event_id}/rescan", response_model=ScanBatchResultOut)
def rescan_event(
    event_id: int,
    session: Session = Depends(session_dep),
    source: InstagramSource = Depends(source_dep),
    settings: Settings = Depends(get_settings),
) -> ScanBatchResultOut:
    if EventRepository(session).get(event_id) is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "fiesta"})
    result = RescanEventUseCase(source, session, settings.recent_posts_limit).execute(event_id)
    if isinstance(result, Err):
        raise_for_err(result)
    return ScanBatchResultOut.model_validate(result.value, from_attributes=True)
