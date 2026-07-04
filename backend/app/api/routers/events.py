from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.api.deps import raise_for_err, session_dep, source_dep
from app.api.schemas import (
    EnrichResultOut,
    EventCreate,
    EventOut,
    EventRefreshOut,
    EventUpdate,
    ScanBatchResultOut,
    SyncResultOut,
)
from app.application.tasks import registry as tasks
from app.application.use_cases import (
    EnrichProfilesUseCase,
    ListUsersUseCase,
    RescanEventUseCase,
    SyncDmsUseCase,
)
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


@router.post("/{event_id}/refresh", response_model=EventRefreshOut)
def refresh_event(
    event_id: int,
    session: Session = Depends(session_dep),
    source: InstagramSource = Depends(source_dep),
    settings: Settings = Depends(get_settings),
) -> EventRefreshOut:
    """Re-scan the fiesta's posts (likes + comments) AND sync DMs in one call."""
    if EventRepository(session).get(event_id) is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "fiesta"})

    with tasks.track("refresh", "Actualizando fiesta") as task:
        scan = RescanEventUseCase(source, session, settings.recent_posts_limit).execute(
            event_id, task.progress
        )
        if isinstance(scan, Err):
            task.fail(scan.message or scan.code.value)
            raise_for_err(scan)
        sync = SyncDmsUseCase(source, session).execute(task.progress)
        if isinstance(sync, Err):
            task.fail(sync.message or sync.code.value)
            raise_for_err(sync)
        task.result = {
            "posts": len(scan.value.results),
            "usuarios": scan.value.total_users_found,
            "hilos": sync.value.threads_synced,
        }
        out = EventRefreshOut(
            scan=ScanBatchResultOut.model_validate(scan.value, from_attributes=True),
            sync=SyncResultOut.model_validate(sync.value, from_attributes=True),
        )
    return out


@router.post("/{event_id}/enrich", response_model=EnrichResultOut)
def enrich_event(
    event_id: int,
    session: Session = Depends(session_dep),
    source: InstagramSource = Depends(source_dep),
) -> EnrichResultOut:
    """Fetch follower count / verified / bio for the fiesta's users (slow, opt-in)."""
    if EventRepository(session).get(event_id) is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "fiesta"})
    pks = [u.pk for u in ListUsersUseCase(session).execute(event=event_id)]
    with tasks.track("enrich", "Enriqueciendo perfiles") as task:
        result = EnrichProfilesUseCase(source, session).execute(pks, progress=task.progress)
        if isinstance(result, Err):
            task.fail(result.message or result.code.value)
            raise_for_err(result)
        task.result = {"enriquecidos": result.value}
    return EnrichResultOut(enriched=result.value)
