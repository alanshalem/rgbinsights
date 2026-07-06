from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.api.deps import raise_for_err, session_dep, source_dep
from app.api.schemas import SyncResultOut
from app.application.tasks import registry as tasks
from app.application.use_cases import SyncDmsUseCase, event_counts, state_delta
from app.domain.result import Err
from app.infrastructure.config.settings import Settings, get_settings
from app.infrastructure.instagram.base import InstagramSource

router = APIRouter(prefix="/sync", tags=["sync"])


@router.post("/dms", response_model=SyncResultOut)
def sync_dms(
    force: bool = False,
    event: int | None = None,  # scope the state-delta to the selected fiesta (display only)
    session: Session = Depends(session_dep),
    source: InstagramSource = Depends(source_dep),
    settings: Settings = Depends(get_settings),
) -> SyncResultOut:
    with tasks.track("sync", "Sincronizando DMs") as task:
        before = event_counts(session, event)
        result = SyncDmsUseCase(source, session).execute(
            task.progress, force=force, incremental=settings.dm_incremental
        )
        if isinstance(result, Err):
            task.fail(result.message or result.code.value)
            raise_for_err(result)
        task.result = {
            **state_delta(before, event_counts(session, event)),
            "hilos": result.value.threads_synced,
        }
        out = SyncResultOut.model_validate(result.value, from_attributes=True)
    return out
