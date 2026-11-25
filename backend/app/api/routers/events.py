from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlmodel import Session

from app.api.deps import require_event, session_dep, source_dep, start_job, uow_factory_dep
from app.api.schemas import EventCreate, EventOut, EventUpdate, TaskOut
from app.application.ports import InstagramSource, UnitOfWork, UnitOfWorkFactory
from app.application.tasks import Task, scan_summary
from app.application.use_cases import (
    EnrichProfilesUseCase,
    ListUsersUseCase,
    RescanEventUseCase,
    SyncDmsUseCase,
    event_counts,
    state_delta,
)
from app.application.use_cases.sync import CAPPED_NOTE
from app.domain.traffic_light import TrafficLight
from app.infrastructure.config.settings import Settings, get_settings
from app.infrastructure.persistence import models
from app.infrastructure.persistence.repositories import EventRepository

router = APIRouter(prefix="/events", tags=["events"])


def _to_out(
    event: models.Event, posts_count: int, last_scanned_at: datetime | None = None
) -> EventOut:
    assert event.id is not None
    return EventOut(
        id=event.id,
        name=event.name,
        promo_start=event.promo_start,
        event_date=event.event_date,
        notes=event.notes,
        posts_count=posts_count,
        last_scanned_at=last_scanned_at,
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
    scanned = repo.last_scanned()
    return [_to_out(e, counts.get(e.id or -1, 0), scanned.get(e.id or -1)) for e in repo.list_all()]


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


# The three below are background jobs (202 + the job): progress and the result
# arrive via GET /tasks/stream (SSE) or /tasks/{id}; see app/application/tasks.py.


@router.post("/{event_id}/rescan", response_model=TaskOut, status_code=202)
def rescan_event(
    event_id: int,
    response: Response,
    force: bool = False,
    session: Session = Depends(session_dep),
    source: InstagramSource = Depends(source_dep),
    settings: Settings = Depends(get_settings),
    new_uow: UnitOfWorkFactory = Depends(uow_factory_dep),
) -> TaskOut:
    """Re-scan the fiesta's posts (likes + comments); recently scanned ones are skipped."""
    require_event(session, event_id)
    skip_hours = settings.rescan_skip_hours

    def work(task: Task, uow: UnitOfWork) -> None:
        before = event_counts(uow, event_id)
        batch = task.unwrap(
            RescanEventUseCase(source, uow).execute(
                event_id, task.progress, force=force, skip_hours=skip_hours
            )
        )
        task.set_result(
            {
                **scan_summary(batch, before, event_counts(uow, event_id)),
                **({"salteados": batch.skipped} if batch.skipped else {}),
            }
        )

    return start_job(
        kind="rescan",
        label="Re-escaneando fiesta",
        params={"event_id": event_id, "force": force},
        work=work,
        new_uow=new_uow,
        response=response,
    )


@router.post("/{event_id}/refresh", response_model=TaskOut, status_code=202)
def refresh_event(
    event_id: int,
    response: Response,
    force: bool = False,
    session: Session = Depends(session_dep),
    source: InstagramSource = Depends(source_dep),
    settings: Settings = Depends(get_settings),
    new_uow: UnitOfWorkFactory = Depends(uow_factory_dep),
) -> TaskOut:
    """Re-scan the fiesta's posts (likes + comments) AND sync DMs in one job."""
    require_event(session, event_id)
    skip_hours, incremental = settings.rescan_skip_hours, settings.dm_incremental

    def work(task: Task, uow: UnitOfWork) -> None:
        before = event_counts(uow, event_id)
        scan = task.unwrap(
            RescanEventUseCase(source, uow).execute(
                event_id, task.progress, force=force, skip_hours=skip_hours
            )
        )
        sync = task.unwrap(
            SyncDmsUseCase(source, uow).execute(task.progress, force=force, incremental=incremental)
        )
        task.set_result(
            {
                "posts": len(scan.results),
                "nuevos": scan.total_new_users,
                **state_delta(before, event_counts(uow, event_id)),
                "hilos": sync.threads_synced,
            },
            warning=CAPPED_NOTE if sync.capped else None,
        )

    return start_job(
        kind="refresh",
        label="Actualizando fiesta",
        params={"event_id": event_id, "force": force},
        work=work,
        new_uow=new_uow,
        response=response,
    )


@router.post("/{event_id}/enrich", response_model=TaskOut, status_code=202)
def enrich_event(
    event_id: int,
    response: Response,
    force: bool = False,
    session: Session = Depends(session_dep),
    source: InstagramSource = Depends(source_dep),
    settings: Settings = Depends(get_settings),
    new_uow: UnitOfWorkFactory = Depends(uow_factory_dep),
) -> TaskOut:
    """Fetch follower count / verified / bio for the fiesta's users (slow, opt-in).

    Capped per run and per Argentina-local day; progress is saved in batches,
    so a later run continues with the users still missing ("faltan")."""
    require_event(session, event_id)

    def work(task: Task, uow: UnitOfWork) -> None:
        pks = [u.pk for u in ListUsersUseCase(uow).execute(event=event_id)]
        enriched = task.unwrap(
            EnrichProfilesUseCase(source, uow).execute(
                pks,
                limit=settings.enrich_profiles_per_run,
                progress=task.progress,
                force=force,
                cache_hours=settings.relationship_cache_hours,
                daily_cap=settings.enrich_profiles_per_day,
                tz=settings.local_tz(),
                full_refresh_days=settings.relationship_full_refresh_days,
            )
        )
        rel = "cache" if enriched.relations_cached else enriched.relations
        # Follower coverage of the reds: safest audience for the campaign.
        reds = ListUsersUseCase(uow).execute(event=event_id, status=TrafficLight.RED)
        red_followers = sum(1 for u in reds if u.follows_us)
        task.set_result(
            {
                "relaciones": rel,
                "perfiles": enriched.enriched,
                "faltan": len(uow.users.unenriched(pks)),
                "te siguen": f"{red_followers}/{len(reds)} rojos",
            }
        )

    return start_job(
        kind="enrich",
        label="Enriqueciendo (relación + perfiles)",
        params={"event_id": event_id, "force": force},
        work=work,
        new_uow=new_uow,
        response=response,
    )
