from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlmodel import Session

from app.api.deps import fail_job, session_factory_dep, source_dep, start_job
from app.api.schemas import TaskOut
from app.application.tasks import SessionFactory, Task
from app.application.use_cases import SyncDmsUseCase, event_counts, state_delta
from app.application.use_cases.sync import CAPPED_NOTE
from app.domain.result import Err
from app.infrastructure.config.settings import Settings, get_settings
from app.infrastructure.instagram.base import InstagramSource

router = APIRouter(prefix="/sync", tags=["sync"])


@router.post("/dms", response_model=TaskOut, status_code=202)
def sync_dms(
    response: Response,
    force: bool = False,
    event: int | None = None,  # scope the state-delta to the selected fiesta (display only)
    source: InstagramSource = Depends(source_dep),
    settings: Settings = Depends(get_settings),
    new_session: SessionFactory = Depends(session_factory_dep),
) -> TaskOut:
    """Background job (202 + the job): progress/result via /tasks/stream or /tasks/{id}.

    The result says "aviso" when DM_THREADS_LIMIT cut an incremental sync short."""
    incremental = settings.dm_incremental

    def work(task: Task, session: Session) -> None:
        before = event_counts(session, event)
        result = SyncDmsUseCase(source, session).execute(
            task.progress, force=force, incremental=incremental
        )
        if isinstance(result, Err):
            fail_job(task, result)
            return
        task.set_result(
            {
                **state_delta(before, event_counts(session, event)),
                "hilos": result.value.threads_synced,
                **({"aviso": CAPPED_NOTE} if result.value.capped else {}),
            }
        )

    return start_job(
        kind="sync",
        label="Sincronizando DMs",
        params={"force": force, "event": event},
        work=work,
        session_factory=new_session,
        response=response,
    )
